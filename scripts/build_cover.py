#!/usr/bin/env python3
"""
Compose the Hootbio artwork from the newest link thumbnails.

Two shapes, because Hootbio uses two:

  banner  16:9, for the image on a link card. Measured on the live page: the
          slot renders 476x268 with object-fit: cover and a 4px corner radius.
          This is the roomy one - tiles are genuinely legible here.
  avatar  1:1, for the profile picture. Cropped to a circle and rendered at
          100x100, which is small enough that four tiles is the ceiling and a
          bare mosaic stops reading as TRPL at all, hence the centre monogram.

Only stories that have already published are used; artwork must never give away
tomorrow's announcement.

    python scripts/build_cover.py                                  # banner
    python scripts/build_cover.py --shape avatar --style badge
    python scripts/build_cover.py --style mosaic --preview

Hootbio has no upload API, so the result is written to site/data/ for a human
to download and set by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
LINKS = DATA_DIR / "links.json"
STAMP_PNG = ROOT / "site" / "trpl-stamp-white.png"

BANNER = (1600, 900)     # 16:9 master; Hootbio renders it at 476x268
AVATAR = (1200, 1200)
GUTTER = 8

NIGHT_SKY = (9, 42, 77)
DARK_FOREST = (27, 69, 50)
DEEP_ORANGE = (231, 128, 93)
WHITE = (255, 255, 255)


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------

def load_tiles(limit: int) -> list[Path]:
    if not LINKS.exists():
        print(f"{LINKS} not found - run build_links.py first", file=sys.stderr)
        return []

    data = json.loads(LINKS.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    paths: list[Path] = []
    for item in data.get("items", []):
        if item.get("publishAt", "") > now:
            continue                      # not out yet
        thumb = item.get("thumb")
        if not thumb:
            continue
        p = DATA_DIR / thumb["src"]
        if p.exists() and p not in paths:
            paths.append(p)
        if len(paths) >= limit:
            break
    return paths


def crop(path: Path, w: int, h: int) -> Image.Image:
    """Centre-crop to the target aspect, then resize."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        iw, ih = img.size
        want = w / h
        have = iw / ih
        if have > want:                    # too wide, trim the sides
            new = int(ih * want)
            box = ((iw - new) // 2, 0, (iw - new) // 2 + new, ih)
        else:                              # too tall, trim top and bottom
            new = int(iw / want)
            # Bias slightly above centre: subjects and faces sit high in a frame.
            top = int((ih - new) * 0.4)
            box = (0, top, iw, top + new)
        return img.crop(box).resize((w, h), Image.LANCZOS)


def filler(w: int, h: int, seed: int) -> Image.Image:
    return Image.new("RGB", (w, h), DARK_FOREST if seed % 2 else NIGHT_SKY)


def stamp(side: int) -> Image.Image | None:
    """The TRPL monogram in white.

    Pre-rendered to PNG and committed so this build needs no SVG rasteriser -
    cairosvg pulls in system Cairo, and a silent import failure on the runner
    would have quietly produced artwork with no brand mark on it.
    """
    if not STAMP_PNG.exists():
        print(f"  {STAMP_PNG.name} missing - no monogram")
        return None
    with Image.open(STAMP_PNG) as art:
        return art.convert("RGBA").resize((side, side), Image.LANCZOS)


def corner_mark(canvas: Image.Image, frac: float = 0.19) -> Image.Image:
    """A small monogram on a Dark Forest disc, bottom right."""
    side = int(min(canvas.size) * frac)
    pad = int(side * 0.34)
    cx = canvas.width - pad - side // 2
    cy = canvas.height - pad - side // 2

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2),
              fill=DARK_FOREST + (255,), outline=WHITE + (255,), width=max(3, side // 40))
    out = Image.alpha_composite(canvas.convert("RGBA"), layer)

    mark = stamp(int(side * 0.84))
    if mark:
        out.paste(mark, (cx - mark.width // 2, cy - mark.height // 2), mark)
    return out.convert("RGB")


# --------------------------------------------------------------------------
# banner styles - 16:9
# --------------------------------------------------------------------------

def banner_strip(tiles: list[Path]) -> Image.Image:
    """Four portrait panels across. Reads as a filmstrip of recent work."""
    W, H = BANNER
    canvas = Image.new("RGB", (W, H), NIGHT_SKY)
    n = 4
    tw = (W - GUTTER * (n - 1)) // n
    for i in range(n):
        img = crop(tiles[i], tw, H) if i < len(tiles) else filler(tw, H, i)
        canvas.paste(img, (i * (tw + GUTTER), 0))
    return canvas


def banner_hero(tiles: list[Path]) -> Image.Image:
    """Newest story large on the left, four more stacked two-by-two."""
    W, H = BANNER
    canvas = Image.new("RGB", (W, H), NIGHT_SKY)

    hw = int(W * 0.5)
    canvas.paste(crop(tiles[0], hw, H) if tiles else filler(hw, H, 0), (0, 0))

    sw = (W - hw - GUTTER * 2) // 2
    sh = (H - GUTTER) // 2
    spots = [(hw + GUTTER, 0), (hw + GUTTER * 2 + sw, 0),
             (hw + GUTTER, sh + GUTTER), (hw + GUTTER * 2 + sw, sh + GUTTER)]
    for i, spot in enumerate(spots):
        src = tiles[i + 1] if i + 1 < len(tiles) else None
        canvas.paste(crop(src, sw, sh) if src else filler(sw, sh, i), spot)
    return canvas


def banner_mosaic(tiles: list[Path]) -> Image.Image:
    """Six stories, three across and two down. The most history per pixel."""
    W, H = BANNER
    canvas = Image.new("RGB", (W, H), NIGHT_SKY)
    cols, rows = 3, 2
    tw = (W - GUTTER * (cols - 1)) // cols
    th = (H - GUTTER * (rows - 1)) // rows
    for i in range(cols * rows):
        x = (i % cols) * (tw + GUTTER)
        y = (i // cols) * (th + GUTTER)
        src = tiles[i] if i < len(tiles) else None
        canvas.paste(crop(src, tw, th) if src else filler(tw, th, i), (x, y))
    return canvas


def banner_four(tiles: list[Path]) -> Image.Image:
    """Two by two. Each tile lands at 16:9, so nothing gets squeezed."""
    W, H = BANNER
    canvas = Image.new("RGB", (W, H), NIGHT_SKY)
    tw = (W - GUTTER) // 2
    th = (H - GUTTER) // 2
    for i, spot in enumerate([(0, 0), (W - tw, 0), (0, H - th), (W - tw, H - th)]):
        src = tiles[i] if i < len(tiles) else None
        canvas.paste(crop(src, tw, th) if src else filler(tw, th, i), spot)
    return canvas


def banner_pair(tiles: list[Path]) -> Image.Image:
    """Two stories side by side, for a thin week."""
    W, H = BANNER
    canvas = Image.new("RGB", (W, H), NIGHT_SKY)
    tw = (W - GUTTER) // 2
    for i, x in enumerate([0, W - tw]):
        src = tiles[i] if i < len(tiles) else None
        canvas.paste(crop(src, tw, H) if src else filler(tw, H, i), (x, 0))
    return canvas


def banner_single(tiles: list[Path]) -> Image.Image:
    """One story, full bleed."""
    W, H = BANNER
    return crop(tiles[0], W, H) if tiles else filler(W, H, 0)


def banner_eight(tiles: list[Path]) -> Image.Image:
    """Eight stories, four across and two down. Texture more than content."""
    W, H = BANNER
    canvas = Image.new("RGB", (W, H), NIGHT_SKY)
    cols, rows = 4, 2
    tw = (W - GUTTER * (cols - 1)) // cols
    th = (H - GUTTER * (rows - 1)) // rows
    for i in range(cols * rows):
        x = (i % cols) * (tw + GUTTER)
        y = (i // cols) * (th + GUTTER)
        src = tiles[i] if i < len(tiles) else None
        canvas.paste(crop(src, tw, th) if src else filler(tw, th, i), (x, y))
    return canvas


# --------------------------------------------------------------------------
# avatar styles - 1:1, circular crop
# --------------------------------------------------------------------------

def avatar_quad(tiles: list[Path]) -> Image.Image:
    W, H = AVATAR
    canvas = Image.new("RGB", (W, H), NIGHT_SKY)
    side = (W - GUTTER) // 2
    for i, spot in enumerate([(0, 0), (W - side, 0), (0, H - side), (W - side, H - side)]):
        src = tiles[i] if i < len(tiles) else None
        canvas.paste(crop(src, side, side) if src else filler(side, side, i), spot)
    return canvas


def avatar_badge(tiles: list[Path]) -> Image.Image:
    canvas = avatar_quad(tiles)
    W, _ = AVATAR
    disc = int(W * 0.42)
    cx = cy = W // 2

    box = (cx - disc // 2 - 8, cy - disc // 2 - 8, cx + disc // 2 + 8, cy + disc // 2 + 8)
    canvas.paste(canvas.crop(box).filter(ImageFilter.GaussianBlur(10)), box[:2])

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        (cx - disc // 2, cy - disc // 2, cx + disc // 2, cy + disc // 2),
        fill=DARK_FOREST + (255,), outline=WHITE + (255,), width=6)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB")

    mark = stamp(int(disc * 0.86))
    if mark:
        canvas.paste(mark, (cx - mark.width // 2, cy - mark.height // 2), mark)
    return canvas


BANNER_STYLES = {"strip": banner_strip, "hero": banner_hero,
                 "mosaic": banner_mosaic, "eight": banner_eight,
                 "four": banner_four, "pair": banner_pair, "single": banner_single}
AVATAR_STYLES = {"quad": avatar_quad, "badge": avatar_badge}

TILES_NEEDED = {"strip": 4, "hero": 5, "mosaic": 6, "eight": 8,
                "four": 4, "pair": 2, "single": 1, "quad": 4, "badge": 4}

# What to step down to when there is not enough imagery, best first. `strip` is
# omitted deliberately: at four stories a 2x2 reads far better than four tall
# panels, which squeeze portraits and crop the life out of landscapes.
BANNER_LADDER = ["eight", "mosaic", "hero", "four", "pair", "single"]
AVATAR_LADDER = ["badge", "quad"]


def circular_mask(size: int) -> Image.Image:
    scale = 4
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=255)
    return big.resize((size, size), Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shape", choices=["banner", "avatar"], default="banner")
    ap.add_argument("--style", default=None,
                    help="banner: strip|hero|mosaic|eight   avatar: quad|badge")
    ap.add_argument("--mark", action="store_true",
                    help="banner only - add the monogram in the bottom corner")
    ap.add_argument("--out", default=None)
    ap.add_argument("--preview", action="store_true",
                    help="also write the artwork at the size Hootbio renders it")
    args = ap.parse_args()

    styles = BANNER_STYLES if args.shape == "banner" else AVATAR_STYLES
    style = args.style or ("mosaic" if args.shape == "banner" else "badge")
    if style not in styles:
        print(f"--style {style} is not valid for {args.shape}: "
              f"choose from {', '.join(sorted(styles))}", file=sys.stderr)
        return 2

    tiles = load_tiles(TILES_NEEDED[style])
    if not tiles:
        print("No published link thumbnails available yet.", file=sys.stderr)
        return 1

    # Rather than pad a six-up with flat colour blocks, step down to a layout
    # the available imagery actually fills. Early on, or after a quiet week,
    # there simply are not six linked stories with pictures.
    if len(tiles) < TILES_NEEDED[style]:
        ladder = BANNER_LADDER if args.shape == "banner" else AVATAR_LADDER
        fits = [s for s in ladder if TILES_NEEDED[s] <= len(tiles)]
        if fits and fits[0] != style:
            print(f"only {len(tiles)} tile(s) available - using "
                  f"'{fits[0]}' instead of '{style}'")
            style = fits[0]

    print(f"{len(tiles)} tile(s) into '{style}': "
          + ", ".join(t.name for t in tiles))

    canvas = styles[style](tiles)
    if args.mark and args.shape == "banner":
        canvas = corner_mark(canvas)

    out = Path(args.out) if args.out else DATA_DIR / (
        "cover.jpg" if args.shape == "banner" else "avatar.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "JPEG", quality=90, optimize=True)
    print(f"wrote {out} ({canvas.width}x{canvas.height}, {out.stat().st_size // 1024} KB)")

    if args.preview:
        if args.shape == "banner":
            small = canvas.resize((476, 268), Image.LANCZOS)
        else:
            small = canvas.resize((100, 100), Image.LANCZOS).convert("RGBA")
            small.putalpha(circular_mask(100))
        pv = out.with_name(out.stem + "-preview.png")
        small.save(pv)
        print(f"wrote {pv} (as Hootbio renders it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
