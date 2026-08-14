#!/usr/bin/env python3
"""
Build site/data/links.json - the feed behind the link-in-bio page that hangs off
hootbio.com/trlibrary.

Hootsuite does not push posted links into Hootbio and offers no widget, so this
reconstructs the same thing from the calendar snapshot: take recent posts that
mention a URL, resolve the ow.ly shortlink to its real destination, read that
page's own headline, and group the six per-network variants of one story into a
single card.

Scheduled posts are included with their send time. The page hides them until
that moment passes and reveals them client-side, so a link goes live on time
even though this build only runs twice a day.

Run after build_calendar.py - it reads that script's output.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
MEDIA_DIR = DATA_DIR / "media"
CALENDAR = DATA_DIR / "calendar.json"
CACHE = DATA_DIR / "link-cache.json"
OUT = DATA_DIR / "links.json"

MAX_STORIES = 20            # published stories shown; scheduled ones are extra
REVEAL_HORIZON_HOURS = 36   # how far ahead to carry, for the client-side reveal
LOOKBACK_DAYS = 400
HEADLINE_MAX = 90
BLURB_MAX = 150

# Hootsuite's own shortener, plus the usual suspects, all need a redirect chase.
SHORTENERS = {"ow.ly", "hoot.ly", "bit.ly", "buff.ly", "t.co", "lnkd.in", "trib.al"}

# Every TRPL post ends with the same call to action. It is not the story, so it
# must never become a card - but it also must not disqualify the real link.
CTA_URL = re.compile(r"^https?://(www\.)?trlibrary\.com/?(visit/?)?$", re.I)

# Lines that are pure boilerplate when deriving fallback copy: the CTA, or a
# line that is nothing but a bare URL.
BOILERPLATE_LINE = re.compile(r"^(https?://\S+|trlibrary\.com\S*)$", re.I)

UA = "TRPL-SocialCalendar/1.0 (+https://socialcalendar.labs.trlibrary.com)"

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)

# Posts routinely write a link the way a person reads it, with no scheme:
#   More: trlibrary.com/tr/presidency/conservation/bird-reserves
# Those are real links and have to be caught. The lookbehind keeps us out of
# email addresses (hello@trlibrary.com) and the TLD list keeps us off ordinary
# prose and decimals.
BARE_URL = re.compile(
    r"(?<![\w@.\-/])"
    # ly/gl/me/be/to are here because the shorteners live on them: ow.ly,
    # bit.ly, buff.ly, goo.gl, fb.me, youtu.be.
    r"((?:[a-z0-9][a-z0-9\-]*\.)+"
    r"(?:com|org|net|gov|edu|info|io|co|us|uk|ca|ly|gl|me|be|to))"
    r"(/[^\s<>\"')\]]*)?",
    re.I,
)

TRAILING = ".,;:!?)\"'»”’"


def extract_urls(text: str) -> list[str]:
    """All links in a post, scheme-ful or not, in the order they appear."""
    found: list[str] = []

    def take(m):
        found.append(m.group(0))
        return " "  # blank it out so the bare-domain pass cannot re-match it

    remainder = URL_RE.sub(take, text or "")
    for m in BARE_URL.finditer(remainder):
        found.append("https://" + m.group(0))

    return [u.rstrip(TRAILING) for u in found if len(u.rstrip(TRAILING)) > 10]


# --------------------------------------------------------------------------
# link resolution
# --------------------------------------------------------------------------

# Bump when a change would make previously cached metadata wrong. v2 fixed
# UTF-8 being decoded as Latin-1, so every title cached under v1 is suspect.
CACHE_VERSION = 2


def load_cache() -> dict:
    if CACHE.exists():
        try:
            raw = json.loads(CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("  link cache was corrupt, starting fresh")
            return {"_v": CACHE_VERSION}
        if raw.get("_v") == CACHE_VERSION:
            return raw
        print(f"  link cache is v{raw.get('_v')}, rebuilding at v{CACHE_VERSION}")
    return {"_v": CACHE_VERSION}


def host_of(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url, flags=re.I).split("/")[0].lower()


def _meta(pattern: str, head: str) -> str | None:
    m = re.search(pattern, head, re.I | re.S)
    return html.unescape(m.group(1)).strip() if m else None


def resolve(url: str, cache: dict) -> dict:
    """Follow redirects and read the destination's own title and image.

    Cached by the URL we started from: shortlinks are permanent, so once a
    story is resolved it never needs fetching again.
    """
    if url in cache:
        return cache[url]

    entry: dict = {"final": url, "title": None, "description": None, "image": None}
    try:
        resp = requests.get(
            url,
            timeout=20,
            allow_redirects=True,
            headers={"User-Agent": UA, "Accept": "text/html,*/*"},
        )
        entry["final"] = resp.url

        # requests falls back to ISO-8859-1 for any text/* response that does
        # not declare a charset, which silently mangles UTF-8: em dashes and
        # curly quotes come out as "â" and "Snøhetta" as "SnÃ¸hetta". Sniff the
        # real encoding whenever the header did not actually tell us one.
        if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        head = resp.text[:200_000]

        entry["title"] = (
            _meta(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', head)
            or _meta(r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)', head)
            or _meta(r"<title[^>]*>(.*?)</title>", head)
        )
        entry["description"] = (
            _meta(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', head)
            or _meta(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', head)
        )
        entry["image"] = _meta(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', head
        )
        entry["site"] = _meta(
            r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', head
        )
        print(f"  resolved {url} -> {host_of(entry['final'])}")
    except requests.RequestException as exc:
        # A dead link still deserves a card; we just fall back to the post copy.
        print(f"  could not resolve {url}: {type(exc).__name__}")

    cache[url] = entry
    return entry


# --------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------

def clean_copy(text: str) -> str:
    """Strip URLs, the standing CTA, and the trailing hashtag block."""
    body = BARE_URL.sub(" ", URL_RE.sub(" ", text or ""))
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or BOILERPLATE_LINE.match(stripped):
            continue
        # A line that is nothing but hashtags is a tag block, not a sentence.
        if stripped and all(w.startswith("#") for w in stripped.split()):
            continue
        lines.append(stripped)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def first_sentence(text: str, limit: int) -> str:
    if not text:
        return ""
    m = re.search(r"^(.{20,}?[.!?])(\s|$)", text)
    candidate = m.group(1) if m else text
    if len(candidate) <= limit:
        return candidate
    return candidate[:limit].rsplit(" ", 1)[0].rstrip(",;:—- ") + "…"


def split_title(meta: dict) -> tuple[str, str | None]:
    """Separate the headline from the publisher name publishers tack on.

    "Headline — The Wall Street Journal" should read as a headline plus a
    source, not as one long run-on that gets clipped mid-word on a phone.
    """
    title = (meta.get("title") or "").strip()
    publisher = (meta.get("site") or "").strip() or None

    m = re.match(r"^(.{15,}?)\s*[|–—]\s*([^|–—]{2,40})$", title)
    if m:
        title = m.group(1).strip()
        publisher = publisher or m.group(2).strip()
    return title, publisher


def headline_for(title: str, copy: str) -> str:
    """Prefer the destination's own headline; fall back to the post's first line.

    A page title is written to be a headline, which is exactly what a card
    needs. Post copy is written to be read in a feed and rarely trims well.
    """
    if len(title) >= 15:
        return first_sentence(title, HEADLINE_MAX)
    return first_sentence(copy, HEADLINE_MAX) or "Read more"


# Redirect shims: the hostname says nothing useful about who published it.
OPAQUE_HOSTS = {"apple.news", "news.google.com", "flip.it", "l.facebook.com"}


def source_label(host: str, publisher: str | None) -> str:
    """What to print as the source under a headline.

    A hostname is usually the most compact honest label. Two exceptions: a
    redirect shim, where the host tells the reader nothing, and a publisher
    name short enough to sit on one line of a phone-width card.
    """
    if publisher and host in OPAQUE_HOSTS:
        return publisher
    if publisher and len(publisher) <= 25:
        return publisher
    return host


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

def cache_remote_image(url: str) -> dict | None:
    stem = "og" + hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:14]
    for path in MEDIA_DIR.glob(f"{stem}.*"):
        try:
            with Image.open(path) as img:
                return {"src": f"media/{path.name}", "w": img.width, "h": img.height}
        except Exception:
            path.unlink(missing_ok=True)
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": UA})
        resp.raise_for_status()
        with Image.open(io.BytesIO(resp.content)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((1000, 1000), Image.LANCZOS)
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            out = MEDIA_DIR / f"{stem}.jpg"
            img.save(out, "JPEG", quality=78, optimize=True)
            return {"src": f"media/{out.name}", "w": img.width, "h": img.height}
    except Exception as exc:
        print(f"  no preview image from {url}: {type(exc).__name__}")
        return None


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def main() -> int:
    if not CALENDAR.exists():
        print(f"{CALENDAR} not found - run build_calendar.py first", file=sys.stderr)
        return 1

    cal = json.loads(CALENDAR.read_text(encoding="utf-8"))
    profiles = {p["id"]: p for p in cal.get("profiles", [])}
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    cache = load_cache()

    # A story that failed to send should never reach the public page.
    usable = {"SENT", "SCHEDULED"}

    candidates = []
    for post in cal.get("posts", []):
        if post.get("state") not in usable or not post.get("scheduledAt"):
            continue
        when = datetime.fromisoformat(post["scheduledAt"].replace("Z", "+00:00"))
        if when < cutoff:
            continue
        # Ignore the standing trlibrary.com/visit CTA; it is on every post.
        urls = [u for u in extract_urls(post.get("text") or "")
                if not CTA_URL.match(u)]
        if urls:
            candidates.append((post, when, urls[0]))

    print(f"{len(candidates)} post(s) carry a link")

    # Group by resolved destination: one story, six networks, one card.
    stories: dict[str, dict] = {}
    for post, when, url in sorted(candidates, key=lambda c: c[1], reverse=True):
        meta = resolve(url, cache)
        key = meta["final"].split("#")[0]

        story = stories.get(key)
        if story is None:
            story = stories[key] = {
                "url": meta["final"],
                "host": host_of(meta["final"]),
                "_times": [],
                "channels": [],
                "_meta": meta,
                "_copies": [],
                "_media": None,
            }
        # A link recurs: "More: trlibrary.com/tr/badlands" rides fifteen posts
        # spread over two months. Collect every airing and decide afterwards.
        story["_times"].append(post["scheduledAt"])

        prof = profiles.get(post["profileId"], {})
        if prof.get("network") and prof["network"] not in story["channels"]:
            story["channels"].append(prof["network"])

        copy = clean_copy(post.get("text", ""))
        if copy:
            story["_copies"].append(copy)
        if story["_media"] is None and post.get("media"):
            story["_media"] = post["media"][0]

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for story in stories.values():
        times = sorted(story.pop("_times"))
        past = [t for t in times if t <= now_iso]
        # publishAt: earliest airing, so the card appears the moment the story
        # first goes live. latestAt: most recent airing that has ALREADY
        # happened, so a link scheduled to run again next month does not claim
        # to be newer than something published this morning.
        story["publishAt"] = times[0]
        story["latestAt"] = past[-1] if past else times[0]

    ordered = sorted(stories.values(), key=lambda s: s["latestAt"], reverse=True)

    items = []
    for story in ordered:
        meta = story.pop("_meta")
        copies = story.pop("_copies")
        media = story.pop("_media")
        # The shortest variant is the X/Bluesky copy, written to be tight.
        shortest = min(copies, key=len) if copies else ""

        thumb = None
        if media and media.get("src"):
            thumb = {"src": media["src"], "w": media.get("w"), "h": media.get("h")}
        elif meta.get("image"):
            thumb = cache_remote_image(meta["image"])

        title, publisher = split_title(meta)
        blurb = first_sentence(
            (meta.get("description") or "").strip() or shortest, BLURB_MAX
        )
        headline = headline_for(title, shortest)
        # Do not print the same sentence twice on one card.
        if blurb and blurb.rstrip("…").lower() in headline.rstrip("…").lower():
            blurb = ""

        items.append({
            "id": hashlib.sha1(story["url"].encode()).hexdigest()[:12],
            "url": story["url"],
            "host": source_label(story["host"], publisher),
            "headline": headline,
            "blurb": blurb,
            "publishAt": story["publishAt"],
            "latestAt": story["latestAt"],
            "channels": story["channels"],
            "thumb": thumb,
        })

    # The calendar only keeps a fortnight of history, so a story would vanish
    # from here the moment its posts aged out of that window. Merge with what
    # we published last time instead: this file is an archive that outlives the
    # calendar snapshot, and it only ever grows forwards.
    kept_new = {i["id"] for i in items}
    carried = 0
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8")).get("items", [])
        except json.JSONDecodeError:
            previous = []
        for old in previous:
            if old.get("id") in kept_new or not old.get("url"):
                continue
            # Do not resurrect a card whose cached image has since been pruned.
            thumb = old.get("thumb")
            if thumb and not (DATA_DIR / thumb["src"]).exists():
                old["thumb"] = None
            items.append(old)
            carried += 1

    items.sort(key=lambda i: i.get("latestAt") or i["publishAt"], reverse=True)

    # Cap the PUBLISHED stories, not the whole list. Counting scheduled ones
    # against the limit let two months of future posts take every slot, and the
    # page - which hides anything unpublished - came out nearly empty.
    live = [i for i in items if i["publishAt"] <= now_iso][:MAX_STORIES]

    # Carry a short runway of upcoming stories so the page can reveal them at
    # their send time between builds. They are extra, never a substitute.
    horizon = (datetime.now(timezone.utc)
               + timedelta(hours=REVEAL_HORIZON_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    soon = [i for i in items if now_iso < i["publishAt"] <= horizon]

    items = soon + live
    print(f"{carried} story(ies) carried over from the previous build")
    print(f"{len(live)} published (cap {MAX_STORIES}), "
          f"{len(soon)} scheduled within {REVEAL_HORIZON_HOURS}h")

    CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")

    payload = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profile": {
            "name": "Theodore Roosevelt Presidential Library",
            "tagline": "Inspiring leadership, conservation, and courageous "
                       "citizenship through the life and legacy of Theodore Roosevelt.",
            "home": "https://www.trlibrary.com",
        },
        "items": items,
    }
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    live = sum(1 for i in items
               if i["publishAt"] <= datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    print(f"wrote {OUT}: {len(items)} story cards "
          f"({live} live now, {len(items) - live} scheduled)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
