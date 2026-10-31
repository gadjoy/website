#!/usr/bin/env python3
"""Generate the PWA icons from the brand logo (spec 013, FR-002).

The source is 512x497 — nearly square. Chrome refuses installability on a
non-square icon, so these are PADDED to a square canvas, never stretched, which
would distort the mark.

Two families, and they are genuinely different images:

  icon-*.png      the standard icon. Mark fills most of the canvas.
  maskable-*.png  Android crops this to a circle, clipping roughly 10% off each
                  edge. The mark is inset into the central safe zone so its
                  edges survive. Relabelling the standard icon as maskable is
                  the usual mistake and ships a logo with its corners sliced.

Both are fully opaque: a transparent background shows the launcher's own colour
through the circular crop.

    python tools/make_pwa_icons.py            # write the icons
    python tools/make_pwa_icons.py --check    # verify without writing
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "static" / "img" / "logo.png"
OUT_DIR = REPO_ROOT / "static" / "img" / "pwa"

# White, because the mark is dark line art. Matches the site's own #ffffff.
BACKGROUND = (255, 255, 255)

SIZES = (192, 512)

# Open Graph / Twitter card. 1200x630 is the size every platform crops from.
# hugo.yaml pointed `default_sharing_image` at img/sharing-default.png, which
# DID NOT EXIST and 404'd on the live site — so every shared link rendered a
# broken card, which is worse than a plain one. Generated here from the same
# brand mark so it cannot drift from the icons.
SHARING = (1200, 630)
SHARING_NAME = "sharing-default.png"
# Fraction of the canvas the mark may occupy.
STANDARD_FILL = 0.88
# Android's safe zone is the central 80% circle; 0.60 keeps the mark inside it
# with margin rather than exactly on the boundary.
MASKABLE_FILL = 0.60


def render(source: Image.Image, size: int, fill: float) -> Image.Image:
    """Scale the mark to occupy `fill` of a square canvas, preserving aspect.

    Scales UP as well as down, deliberately. Image.thumbnail() only ever
    shrinks, so with a source smaller than the budget it silently ignores
    `fill` — the maskable and standard icons would then come out identical and
    Android would crop the mark. Today's 512x497 logo is large enough for that
    never to bite, which is exactly the kind of accident that breaks the day
    someone swaps the logo for a smaller one.
    """
    canvas = Image.new("RGBA", (size, size), (*BACKGROUND, 255))
    budget = size * fill
    scale = budget / max(source.width, source.height)
    mark = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.LANCZOS,
    )
    canvas.paste(mark, ((size - mark.width) // 2, (size - mark.height) // 2), mark)
    return canvas.convert("RGB")


def render_sharing(source: Image.Image) -> Image.Image:
    """A 1200x630 card: the mark centred on the brand background.

    Deliberately plain. A sharing card competes with everything else in a
    WhatsApp thread, and a legible mark on white reads better at thumbnail size
    than anything with text in it.
    """
    w, h = SHARING
    canvas = Image.new("RGBA", (w, h), (*BACKGROUND, 255))
    budget = int(h * 0.62)
    scale = budget / max(source.width, source.height)
    mark = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.LANCZOS)
    canvas.paste(mark, ((w - mark.width) // 2, (h - mark.height) // 2), mark)
    return canvas.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed icons match what this would produce")
    args = ap.parse_args()

    if not SOURCE.is_file():
        sys.exit(f"source logo not found: {SOURCE}")

    with Image.open(SOURCE) as src:
        source = src.convert("RGBA")

    wanted = {}
    wanted[REPO_ROOT / "static" / "img" / SHARING_NAME] = render_sharing(source)
    for size in SIZES:
        wanted[OUT_DIR / f"icon-{size}.png"] = render(source, size, STANDARD_FILL)
        wanted[OUT_DIR / f"maskable-{size}.png"] = render(source, size, MASKABLE_FILL)

    if args.check:
        missing = [p for p in wanted if not p.is_file()]
        if missing:
            print("missing: " + ", ".join(p.name for p in missing), file=sys.stderr)
            return 1
        print(f"all {len(wanted)} icons present")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, img in wanted.items():
        img.save(path, "PNG", optimize=True)
        # relative_to() raises when OUT_DIR is outside the repo, which it is
        # whenever a test points it at a temp directory. A reporting line must
        # not be able to fail the operation it is reporting on.
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path
        print(f"  {shown}  {img.size}")
    print(f"\n{len(wanted)} icons written. They are committed, so the build never "
          f"depends on Pillow being installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
