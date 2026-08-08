#!/usr/bin/env python3
"""
Compose the Hootbio profile image from the newest link thumbnails.

Hootbio serves that image square and crops it to a circle at 100x100 CSS
pixels, so this is a mosaic tease rather than a legible preview - four tiles is
the practical ceiling before it turns to mush. Everything that has to survive
the crop is kept inside the inscribed circle.

Only stories that have already published are used; a profile picture must never
give away tomorrow's announcement.

    python scripts/build_cover.py                # default style
    python scripts/build_cover.py --style quad --out /tmp/x.jpg

Hootbio has no upload API, so the result is written to site/data/cover.jpg for
a human to download and set by hand.
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

SIZE = 1200          # square master; Hootbio downscales to 100
GUTTER = 10          # Night Sky separator between tiles

NIGHT_SKY = (9, 42, 77)
DARK_FOREST = (27, 69, 50)
DEEP_ORANGE = (231, 128, 93)
WHITE = (255, 255, 255)


def load_tiles(limit: int) -> list[Path]:
    if not LINKS.exists():
        print(f"{LINKS} not found - run build_links.py first", file=sys.stderr)
        return []

    data = json.loads(LINKS.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    paths: list[Path] = []
    for item in data.get("items", []):
        # Never tease something that has not gone out yet.
        if item.get("publishAt", "") > now:
            continue
        thumb = item.get("thumb")
        if not thumb:
            continue
        p = DATA_DIR / thumb["src"]
        if p.exists() and p not in paths:
            paths.append(p)
        if len(paths) >= limit:
            break
    return paths


def square(path: Path, side: int) -> Image.Image:
    """Centre-crop to a square and resize. Faces and subjects sit centrally in
    social imagery, so a centre crop is the safe default."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        edge = min(w, h)
        img = img.crop((
            (w - edge) // 2, (h - edge) // 2,
            (w - edge) // 2 + edge, (h - edge) // 2 + edge,
        ))
        return img.resize((side, side), Image.LANCZOS)


def filler(side: int, seed: int) -> Image.Image:
    """A branded tile for when there are fewer than four usable images."""
    base = DARK_FOREST if seed % 2 == 0 else NIGHT_SKY
    return Image.new("RGB", (side, side), base)


def stamp(side: int) -> Image.Image | None:
    """The TRPL monogram in white.

    Pre-rendered to PNG and committed so this build needs no SVG rasteriser -
    cairosvg pulls in system Cairo, and a silent import failure on the runner
    would have quietly produced a cover with no brand mark on it.
    """
    if not STAMP_PNG.exists():
        print(f"  {STAMP_PNG.name} missing - cover will have no monogram")
        return None
    with Image.open(STAMP_PNG) as art:
        return art.convert("RGBA").resize((side, side), Image.LANCZOS)


def circular_mask(size: int) -> Image.Image:
    """Anti-aliased circle, built oversized then downsampled."""
    scale = 4
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=255)
    return big.resize((size, size), Image.LANCZOS)


# --------------------------------------------------------------------------
# styles
# --------------------------------------------------------------------------

def style_quad(tiles: list[Path]) -> Image.Image:
    """Four images in quadrants, Night Sky gutters."""
    canvas = Image.new("RGB", (SIZE, SIZE), NIGHT_SKY)
    side = (SIZE - GUTTER) // 2
    spots = [(0, 0), (SIZE - side, 0), (0, SIZE - side), (SIZE - side, SIZE - side)]
    for i, spot in enumerate(spots):
        img = square(tiles[i], side) if i < len(tiles) else filler(side, i)
        canvas.paste(img, spot)
    return canvas


def style_badge(tiles: list[Path]) -> Image.Image:
    """Quadrants with the TRPL monogram held in the centre.

    An avatar's first job is recognition. Four unrelated photographs at 100px
    do not say "Theodore Roosevelt Presidential Library" to anyone.
    """
    canvas = style_quad(tiles)

    disc = int(SIZE * 0.42)
    cx = cy = SIZE // 2

    # Soften what sits under the badge so the mark stays legible.
    box = (cx - disc // 2 - 8, cy - disc // 2 - 8, cx + disc // 2 + 8, cy + disc // 2 + 8)
    region = canvas.crop(box).filter(ImageFilter.GaussianBlur(10))
    canvas.paste(region, box[:2])

    ring = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(ring)
    d.ellipse((cx - disc // 2, cy - disc // 2, cx + disc // 2, cy + disc // 2),
              fill=DARK_FOREST + (255,), outline=WHITE + (255,), width=6)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), ring).convert("RGB")

    mark = stamp(int(disc * 0.86))
    if mark:
        canvas.paste(mark, (cx - mark.width // 2, cy - mark.height // 2), mark)
    return canvas


def style_three(tiles: list[Path]) -> Image.Image:
    """One large image with two stacked beside it, over a branded base."""
    canvas = Image.new("RGB", (SIZE, SIZE), NIGHT_SKY)
    big = SIZE - (SIZE // 3) - GUTTER
    small = SIZE - big - GUTTER

    if tiles:
        canvas.paste(square(tiles[0], big), (0, (SIZE - big) // 2))
    if len(tiles) > 1:
        canvas.paste(square(tiles[1], small), (big + GUTTER, 0))
    if len(tiles) > 2:
        canvas.paste(square(tiles[2], small), (big + GUTTER, small + GUTTER))

    bar = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(bar).ellipse(
        (6, 6, SIZE - 7, SIZE - 7), outline=DEEP_ORANGE + (255,), width=14
    )
    return Image.alpha_composite(canvas.convert("RGBA"), bar).convert("RGB")


STYLES = {"quad": style_quad, "badge": style_badge, "three": style_three}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", choices=sorted(STYLES), default="badge")
    ap.add_argument("--out", default=str(DATA_DIR / "cover.jpg"))
    ap.add_argument("--preview", action="store_true",
                    help="also write a 100px circular crop, i.e. what Hootbio shows")
    args = ap.parse_args()

    tiles = load_tiles(4)
    if not tiles:
        print("No published link thumbnails available yet.", file=sys.stderr)
        return 1
    print(f"{len(tiles)} tile(s): " + ", ".join(t.name for t in tiles))

    canvas = STYLES[args.style](tiles)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "JPEG", quality=92, optimize=True)
    print(f"wrote {out} ({SIZE}x{SIZE}, {out.stat().st_size // 1024} KB)")

    if args.preview:
        small = canvas.resize((100, 100), Image.LANCZOS).convert("RGBA")
        small.putalpha(circular_mask(100))
        pv = out.with_name(out.stem + "-preview.png")
        small.save(pv)
        print(f"wrote {pv} (what Hootbio actually renders)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
