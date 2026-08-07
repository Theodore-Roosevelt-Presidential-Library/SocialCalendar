#!/usr/bin/env python3
"""
Pull the upcoming Hootsuite schedule and write the static payload the web view
reads: site/data/calendar.json plus locally cached preview images.

Media has to be cached rather than hot-linked. Hootsuite hands out pre-signed S3
URLs that expire in minutes, and this job only runs twice a day, so any URL we
embedded would be dead long before anyone loaded the page.

Environment:
  HOOTSUITE_CLIENT_ID       required
  HOOTSUITE_CLIENT_SECRET   required
  HOOTSUITE_REFRESH_TOKEN   required, single-use, rotated by this script
  SECRETS_PAT               required in CI - fine-grained PAT, Secrets: RW
  GITHUB_REPOSITORY         set automatically by Actions
  DAYS_BACK                 default 14
  DAYS_AHEAD                default 90
  SKIP_SECRET_ROTATION      set to 1 for local dry runs (see --local)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageOps

from hootsuite import Hootsuite, HootsuiteError, refresh_access_token
from github_secret import RepoSecrets, SecretWriteError

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
MEDIA_DIR = DATA_DIR / "media"

PREVIEW_MAX_EDGE = 1000  # plenty for a card preview, keeps the repo small
PREVIEW_QUALITY = 78

REFRESH_TOKEN_SECRET = "HOOTSUITE_REFRESH_TOKEN"


# --------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------

def _cached(stem: str) -> dict | None:
    """Return the manifest entry for an already-downloaded asset, if sound."""
    for path in MEDIA_DIR.glob(f"{stem}.*"):
        try:
            with Image.open(path) as img:
                return {"src": f"media/{path.name}", "w": img.width, "h": img.height}
        except Exception:
            path.unlink(missing_ok=True)  # corrupt cache entry, refetch
    return None


def _download_and_store(url: str, stem: str, label: str) -> dict | None:
    try:
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  could not download {label}: {exc}")
        return None

    if resp.headers.get("Content-Type", "").startswith("video/"):
        return None  # the poster frame is fetched separately

    try:
        with Image.open(io.BytesIO(resp.content)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE), Image.LANCZOS)
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            out = MEDIA_DIR / f"{stem}.jpg"
            img.save(out, "JPEG", quality=PREVIEW_QUALITY, optimize=True)
            return {"src": f"media/{out.name}", "w": img.width, "h": img.height}
    except Exception as exc:
        print(f"  could not decode {label}: {exc}")
        return None


def cache_media(client: Hootsuite, media_id: str) -> dict | None:
    """Resolve a Hootsuite media id, download it, and downscale for preview."""
    stem = hashlib.sha1(str(media_id).encode()).hexdigest()[:16]
    hit = _cached(stem)
    if hit:
        return hit

    url = client.media_download_url(media_id)
    if not url:
        return None
    return _download_and_store(url, stem, f"media {media_id}")


def cache_media_url(url: str) -> dict | None:
    """Cache an attachment given only a URL.

    Keyed on the path with the query string stripped, because these arrive as
    pre-signed S3 links whose signature changes on every API call - hashing the
    whole URL would re-download the same picture every run.
    """
    stem = hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:16]
    hit = _cached(stem)
    if hit:
        return hit
    return _download_and_store(url, stem, "attachment")


def prune_media(referenced: set[str]) -> None:
    if not MEDIA_DIR.exists():
        return
    removed = 0
    for path in MEDIA_DIR.iterdir():
        if path.is_file() and f"media/{path.name}" not in referenced:
            path.unlink()
            removed += 1
    if removed:
        print(f"pruned {removed} unreferenced media file(s)")


# --------------------------------------------------------------------------
# transform
# --------------------------------------------------------------------------

def normalize_message(msg: dict, client: Hootsuite) -> dict:
    media: list[dict] = []
    for item in msg.get("media") or []:
        is_video = bool(item.get("videoOptions"))
        # For video, the poster frame is a separate asset; for stills the
        # thumbnail is a cheaper download than the full-resolution original.
        source_id = item.get("thumbnailId") or item.get("id")
        entry = cache_media(client, source_id) if source_id else None
        if entry is None and item.get("id") and source_id != item.get("id"):
            entry = cache_media(client, item["id"])
        if entry:
            entry["kind"] = "video" if is_video else "image"
            if item.get("altText"):
                entry["altText"] = item["altText"]
            media.append(entry)

    # `mediaUrls` is NOT a separate set of attachments - Hootsuite describes the
    # same pictures twice, once by id in `media` and once by URL here. Appending
    # both showed every image on a post two times. Only fall back to it when
    # `media` gave us nothing at all.
    if not media:
        for extra in msg.get("mediaUrls") or []:
            url = extra.get("thumbnailUrl") or extra.get("url")
            entry = cache_media_url(url) if url else None
            if entry:
                entry["kind"] = "image"
                media.append(entry)

    # Belt and braces: never let the same picture appear twice on one post.
    seen_src: set[str] = set()
    media = [m for m in media if not (m["src"] in seen_src or seen_src.add(m["src"]))]

    profile_id = str((msg.get("socialProfile") or {}).get("id") or "")

    return {
        # A message targeting several profiles reuses one id, so a card's
        # identity is the (message, profile) pair.
        "id": f"{msg.get('id')}:{profile_id}",
        "profileId": profile_id,
        "scheduledAt": msg.get("scheduledSendTime"),
        "state": msg.get("state") or "SCHEDULED",
        "text": msg.get("text") or "",
        "media": media,
        "tags": [t.get("name") for t in (msg.get("tags") or []) if t.get("name")],
        "postUrl": msg.get("postUrl"),
        "sequence": msg.get("sequenceNumber"),
    }


def build_payload(client: Hootsuite, days_back: int, days_ahead: int) -> dict:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days_back)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = (now + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    print(f"window: {start:%Y-%m-%d} -> {end:%Y-%m-%d}")

    profiles = []
    for prof in client.social_profiles():
        profiles.append(
            {
                "id": str(prof.get("id")),
                "name": prof.get("socialNetworkUsername")
                or prof.get("name")
                or f"Profile {prof.get('id')}",
                "network": (prof.get("type") or "OTHER").upper(),
                "url": prof.get("externalURL"),
                "avatar": prof.get("avatarUrl"),
            }
        )
    print(f"{len(profiles)} social profile(s)")

    posts: list[dict] = []
    seen: set[str] = set()
    for msg in client.messages(start, end):
        norm = normalize_message(msg, client)
        if norm["id"] in seen:
            continue
        seen.add(norm["id"])
        posts.append(norm)

    posts.sort(key=lambda p: (p.get("scheduledAt") or "", p["id"]))
    print(f"{len(posts)} message(s) total")

    tags = sorted({t for p in posts for t in p["tags"]})

    return {
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "hootsuite-rest-api",
        "window": {
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "profiles": profiles,
        "tags": tags,
        "posts": posts,
    }


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--local",
        action="store_true",
        help="Dry run outside CI: read the refresh token from HOOTSUITE_REFRESH_TOKEN "
             "and print the rotated one instead of writing it to a GitHub secret.",
    )
    args = parser.parse_args()

    try:
        client_id = os.environ["HOOTSUITE_CLIENT_ID"]
        client_secret = os.environ["HOOTSUITE_CLIENT_SECRET"]
        refresh_token = os.environ["HOOTSUITE_REFRESH_TOKEN"]
    except KeyError as exc:
        print(
            f"Missing required environment variable {exc}. "
            "See SETUP.md for the three Hootsuite secrets.",
            file=sys.stderr,
        )
        return 2

    rotate_to_secret = not args.local and os.environ.get("SKIP_SECRET_ROTATION") != "1"
    store: RepoSecrets | None = None

    if rotate_to_secret:
        repo = os.environ.get("GITHUB_REPOSITORY")
        pat = os.environ.get("SECRETS_PAT")
        if not repo or not pat:
            print(
                "SECRETS_PAT and GITHUB_REPOSITORY are required so the rotated "
                "refresh token can be persisted. See SETUP.md.",
                file=sys.stderr,
            )
            return 2
        store = RepoSecrets(repo, pat)
        # Verify write access BEFORE consuming the single-use refresh token.
        try:
            store.preflight()
        except SecretWriteError as exc:
            print(f"Preflight failed, refresh token untouched: {exc}", file=sys.stderr)
            return 2
        print("secret write access confirmed")

    try:
        tokens = refresh_access_token(client_id, client_secret, refresh_token)
    except HootsuiteError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print("access token acquired")

    if store is not None:
        try:
            store.put(REFRESH_TOKEN_SECRET, tokens.refresh_token)
            print(f"rotated {REFRESH_TOKEN_SECRET}")
        except SecretWriteError as exc:
            # The old token is already spent, so this is unrecoverable without a
            # human. Say so loudly and without leaking the token into the log.
            print(
                f"CRITICAL: obtained a new refresh token but could not store it "
                f"({exc}). The chain is broken - re-run scripts/bootstrap_auth.py "
                f"and update {REFRESH_TOKEN_SECRET} by hand.",
                file=sys.stderr,
            )
            return 4
    elif args.local:
        print("\n--local: store this as your new HOOTSUITE_REFRESH_TOKEN:")
        print(f"  {tokens.refresh_token}\n")

    client = Hootsuite(tokens.access_token)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    payload = build_payload(
        client,
        days_back=int(os.environ.get("DAYS_BACK", "14")),
        days_ahead=int(os.environ.get("DAYS_AHEAD", "90")),
    )

    referenced = {
        m["src"]
        for p in payload["posts"]
        for m in p["media"]
        if not m.get("remote")
    }
    prune_media(referenced)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "calendar.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    shutil.move(tmp, out)

    size_kb = out.stat().st_size / 1024
    print(f"wrote {out.relative_to(ROOT)} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
