"""Screenshot comparison (spec 012, FR-005).

Deliberately a small function with its own tests rather than a library call:
SC-002 and SC-003 require the threshold to be proven in BOTH directions, and a
threshold only ever demonstrated in the passing direction might as well be
infinity.

What it must tolerate: antialiasing and subpixel text rendering, which differ
between machines and between font-cache states on the same machine.
What it must not tolerate: an element moving.

Those pull in opposite directions, so the comparison is two-stage:

  * per-pixel channel tolerance (CHANNEL_TOLERANCE) ignores a pixel whose
    channels all differ slightly — the signature of antialiasing;
  * the ratio of pixels that exceed it is compared to MAX_DIFF_RATIO.

A 10px shift moves hard edges across many pixels at once and blows past the
ratio; antialiasing perturbs edge pixels by a few levels and is absorbed.
"""
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops

# A pixel is "unchanged" if every channel is within this many levels. Text
# antialiasing between machines moves channels by a handful of levels.
CHANNEL_TOLERANCE = 32
# Fraction of pixels allowed to exceed that before the comparison fails.
# 0.2% absorbs a re-rendered glyph edge; a shifted element is orders above it.
MAX_DIFF_RATIO = 0.002


@dataclass
class Comparison:
    ok: bool
    ratio: float
    reason: str
    size_changed: bool = False


def compare(baseline: Path, candidate: Path, diff_out: Path = None) -> Comparison:
    with Image.open(baseline) as a_img, Image.open(candidate) as b_img:
        a = a_img.convert("RGB")
        b = b_img.convert("RGB")

        if a.size != b.size:
            # A size change is a layout change by definition, and comparing
            # different-sized images pixelwise is meaningless. Reported
            # distinctly so the log says what happened (CON-VER-005).
            return Comparison(
                False, 1.0,
                f"size changed: baseline {a.size}, candidate {b.size}",
                size_changed=True)

        diff = ImageChops.difference(a, b)
        # Per-pixel max across channels, then threshold.
        mono = diff.convert("L", matrix=None) if diff.mode == "L" else max_channel(diff)
        mask = mono.point(lambda v: 255 if v > CHANNEL_TOLERANCE else 0)
        changed = sum(1 for v in mask.tobytes() if v)
        total = a.size[0] * a.size[1]
        ratio = changed / total

        if diff_out is not None and ratio > MAX_DIFF_RATIO:
            diff_out.parent.mkdir(parents=True, exist_ok=True)
            mask.save(diff_out)

        if ratio > MAX_DIFF_RATIO:
            return Comparison(
                False, ratio,
                f"{changed} of {total} pixels ({ratio:.3%}) differ by more than "
                f"{CHANNEL_TOLERANCE} levels, above the {MAX_DIFF_RATIO:.3%} budget")
        return Comparison(True, ratio, f"{ratio:.4%} of pixels differ (within budget)")


def max_channel(rgb_diff: Image.Image) -> Image.Image:
    """Greyscale image of the LARGEST per-channel difference.

    Not ImageChops/convert("L"), which applies luminance weights — a change
    confined to the blue channel would be scaled down to 11% of its magnitude
    and could slip under the tolerance.
    """
    r, g, b = rgb_diff.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b)
