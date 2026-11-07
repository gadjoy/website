"""Obfuscate device/customer identifiers inside published images, in place.

The repair photo is legitimate evidence of the work — only the identifier block has to
go, so this redacts rather than deletes (specs/006-gallery-lightbox/ FR-007).

Redaction is a COARSE MOSAIC, not a blur. A fine-grained pixelation of known-format text
(15 digits, fixed glyph set) is in principle attackable by rendering candidates and
matching blocks; collapsing the region to a handful of blocks and then blurring destroys
the information outright. The label ("IMEI (slot 1)") is deliberately left readable — a
visible redaction is honest about what was removed, and the photo still reads as a repair
proof shot.

Regions can be given three ways:
  --auto              derive boxes from OCR (digit runs, MAC addresses, serial tokens)
  --frac x,y,w,h      fractional 0..1 box, repeatable — robust to rescaling, and the
                      practical option when OCR reads the label but not the value
  --box x,y,w,h       absolute pixel box, repeatable

Usage:
    python migration/scripts/redact_device_identifiers.py IMG --auto
    python migration/scripts/redact_device_identifiers.py IMG --frac 0.1,0.45,0.8,0.25
    python migration/scripts/redact_device_identifiers.py IMG --auto --dry-run
"""
import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))

from device_identifiers import ocr_words, _normalise_digits  # noqa: E402

# Collapse each redacted region to at most this many blocks on its long edge. Low on
# purpose: the point is to destroy the glyphs, not to stylise them.
MAX_BLOCKS = 5

VALUE_RE = re.compile(r"^(?:\d[\d\s\-/]{12,}|(?:[0-9a-f]{2}:){5}[0-9a-f]{2}|[A-Z0-9]{8,})$", re.I)
LABEL_RE = re.compile(r"\b(imei|meid|serial|s/n)\b", re.I)

# Refuse to write if --auto wants to obscure more than this share of the frame. Over-
# redaction is the safe failure mode for privacy but not for the photo: past this point
# the image has stopped being evidence of a repair, so a human should look instead.
MAX_REDACT_FRACTION = 0.25


def mosaic(im: Image.Image, box) -> Image.Image:
    """Destroy detail inside box = (left, top, right, bottom)."""
    left, top, right, bottom = (int(v) for v in box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(im.width, right), min(im.height, bottom)
    if right <= left or bottom <= top:
        return im
    region = im.crop((left, top, right, bottom))
    w, h = region.size
    bw, bh = max(1, min(MAX_BLOCKS, w // 6 or 1)), max(1, min(MAX_BLOCKS, h // 6 or 1))
    region = region.resize((bw, bh), Image.BOX).resize((w, h), Image.NEAREST)
    region = region.filter(ImageFilter.GaussianBlur(radius=max(1.0, min(w, h) / 12)))
    im.paste(region, (left, top))
    return im


def auto_boxes(path: Path, pad=3):
    """Boxes covering identifier VALUES.

    Two things are needed, because About screens come in two layouts and guessing wrong
    leaves the identifier on screen:

      label-above-value   (newer Samsung/Android "Serial number\\n R9ZT…")
      label-left-value-right (two-column table: "Serial number | RZ8J50WTJRR")

    An earlier version only swept the band *below* each label. On a two-column layout that
    missed the value entirely — `2023/05/image-4.webp` kept a fully legible serial through
    a redaction pass. So each label now gets one band that starts at the label and runs to
    the right edge of the frame, tall enough to include the next line: that covers the
    same-row value and the below-label value in one shape.

    It over-redacts (the label itself, and boilerplate like "View the SIM card status,
    IMEI, and other information"). That is the correct direction to err, and the frame
    fraction is capped by MAX_REDACT_FRACTION so it cannot run away.
    """
    _text, words = ocr_words(path)
    with Image.open(path) as im:
        width = im.width

    boxes, labels = [], []
    for w in words:
        tok = w["text"].strip()
        if LABEL_RE.search(tok):
            labels.append(w)
        norm = _normalise_digits(tok)
        if VALUE_RE.match(tok) or re.fullmatch(r"\d{14,16}", norm):
            boxes.append((w["left"] - pad, w["top"] - pad,
                          w["left"] + w["width"] + pad, w["top"] + w["height"] + pad))

    for lb in labels:
        h = max(lb["height"], 8)
        boxes.append((
            lb["left"] - pad,                      # from the label...
            lb["top"] - pad,                       # ...its own row (value may sit right)
            width,                                 # ...out to the right edge
            # ...through the following line. 2.3x left three "IMEI (slot 2)" values
            # uncovered where OCR reported a short label height, so the band stopped
            # above the digits; 3.0x covers the value row with margin.
            lb["top"] + int(h * 3.0),
        ))
    return boxes


def parse_box(spec, size=None, fractional=False):
    parts = [float(v) for v in spec.split(",")]
    if len(parts) != 4:
        raise ValueError(f"expected x,y,w,h — got {spec!r}")
    x, y, w, h = parts
    if fractional:
        if not size:
            raise ValueError("fractional box needs image size")
        x, y, w, h = x * size[0], y * size[1], w * size[0], h * size[1]
    return (x, y, x + w, y + h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--auto", action="store_true", help="derive boxes from OCR")
    ap.add_argument("--box", action="append", default=[], metavar="x,y,w,h")
    ap.add_argument("--frac", action="append", default=[], metavar="x,y,w,h")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quality", type=int, default=92)
    args = ap.parse_args()

    path = Path(args.image)
    with Image.open(path) as src:
        im = src.convert("RGB")
        fmt = src.format

    boxes = []
    if args.auto:
        boxes += auto_boxes(path)
    boxes += [parse_box(s, im.size, False) for s in args.box]
    boxes += [parse_box(s, im.size, True) for s in args.frac]

    if not boxes:
        print(f"{path.name}: no regions to redact")
        return 1

    # Clamp and measure before writing anything.
    clamped = []
    for left, top, right, bottom in boxes:
        left, top = max(0, int(left)), max(0, int(top))
        right, bottom = min(im.width, int(right)), min(im.height, int(bottom))
        if right > left and bottom > top:
            clamped.append((left, top, right, bottom))
    boxes = clamped
    # Re-check AFTER clamping. A box wholly outside the frame clamps to nothing,
    # and without this the run fell through to im.save(): a lossy re-encode of
    # an unchanged image, reported as success.
    if not boxes:
        print(f"{path.name}: no regions to redact (every box fell outside the frame)")
        return 1
    covered = sum((r - l) * (b - t) for l, t, r, b in boxes)
    fraction = covered / float(im.width * im.height)

    print(f"{path.name} ({im.width}x{im.height}): {len(boxes)} region(s), "
          f"{fraction:.1%} of frame")
    for b in boxes:
        print(f"    {b}")

    if fraction > MAX_REDACT_FRACTION:
        print(f"    REFUSED: would obscure {fraction:.0%} (> {MAX_REDACT_FRACTION:.0%}) — "
              f"review by hand and pass explicit --box/--frac regions")
        return 2
    if args.dry_run:
        return 0

    for b in boxes:
        im = mosaic(im, b)

    save_kwargs = {"quality": args.quality, "method": 6} if fmt == "WEBP" else {"quality": args.quality}
    im.save(path, fmt, **save_kwargs)
    print(f"    written in place ({fmt})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
