#!/usr/bin/env python3
"""
Build site/data/calendar.json from a raw JSONL capture of Hootsuite planned
content (site/data/_seed_raw.jsonl).

This exists so the site can be populated *before* the OAuth app is registered:
the schedule is captured once through the Hootsuite MCP connector, and this
script turns it into exactly the same payload the GitHub Action produces. Once
the Action is running, build_calendar.py overwrites the output and this script
is no longer used.

Each JSONL line:
  {"id","profileId","profileName","network","scheduledAt","state","text",
   "tags":[],"campaign":null,"postUrl":null,
   "media":[{"url","thumbUrl","kind","durationSec","altText"}]}
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
MEDIA_DIR = DATA_DIR / "media"
RAW = DATA_DIR / "_seed_raw.jsonl"

PREVIEW_MAX_EDGE = 1000
PREVIEW_QUALITY = 78


def cache(url: str) -> dict | None:
    stem = hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:16]
    out = MEDIA_DIR / f"{stem}.jpg"
    if out.exists():
        with Image.open(out) as img:
            return {"src": f"media/{out.name}", "w": img.width, "h": img.height}
    try:
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
        with Image.open(io.BytesIO(resp.content)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE), Image.LANCZOS)
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            img.save(out, "JPEG", quality=PREVIEW_QUALITY, optimize=True)
            return {"src": f"media/{out.name}", "w": img.width, "h": img.height}
    except Exception as exc:
        print(f"  skip media ({type(exc).__name__}: {str(exc)[:90]})")
        return None


def main() -> int:
    if not RAW.exists():
        print(f"{RAW} not found", file=sys.stderr)
        return 1

    rows = []
    for line in RAW.read_text(encoding="utf-8").splitlines():
        line = line.strip().rstrip(",")
        if line:
            rows.append(json.loads(line))
    print(f"{len(rows)} raw record(s)")

    profiles: dict[str, dict] = {}
    posts: list[dict] = []
    seen: set[str] = set()

    for row in rows:
        pid = str(row["profileId"])
        profiles.setdefault(pid, {
            "id": pid,
            "name": row.get("profileName") or f"Profile {pid}",
            "network": (row.get("network") or "OTHER").upper(),
            "url": row.get("profileUrl"),
        })

        # One Hootsuite draft can target several profiles and reuses its id on
        # each, so the identity of a *card* is the (draft, profile) pair.
        key = f"{row['id']}:{pid}"
        if key in seen:
            continue
        seen.add(key)

        media = []
        for m in row.get("media") or []:
            # Prefer the poster frame: it is a still even for video, and it is
            # a far smaller download than the source asset.
            url = m.get("thumbUrl") or m.get("url")
            if not url:
                continue
            entry = cache(url)
            if not entry:
                continue
            entry["kind"] = m.get("kind") or "image"
            if m.get("durationSec"):
                entry["durationSec"] = m["durationSec"]
            if m.get("altText"):
                entry["altText"] = m["altText"]
            media.append(entry)

        tags = list(row.get("tags") or [])
        if row.get("campaign"):
            tags.append(row["campaign"])

        posts.append({
            "id": key,
            "profileId": pid,
            "scheduledAt": row.get("scheduledAt"),
            "state": row.get("state") or "SCHEDULED",
            "text": row.get("text") or "",
            "media": media,
            "tags": tags,
            "postUrl": row.get("postUrl"),
        })

    posts.sort(key=lambda p: (p.get("scheduledAt") or "", p["id"]))
    dates = [p["scheduledAt"] for p in posts if p.get("scheduledAt")]

    payload = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "hootsuite-mcp-seed",
        "window": {"start": min(dates) if dates else None,
                   "end": max(dates) if dates else None},
        "profiles": sorted(profiles.values(), key=lambda p: p["name"]),
        "tags": sorted({t for p in posts for t in p["tags"]}),
        "posts": posts,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "calendar.json"
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}: {len(posts)} posts, "
          f"{len(profiles)} profiles, {out.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
