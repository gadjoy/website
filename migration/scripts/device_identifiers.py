"""Detect device/customer identifiers printed inside published images.

Why this exists: the shop photographed devices' **About** screens as repair proof, so a
handful of before/after images publish the customer's own data — owner name, serial
number, IMEIs, Wi-Fi/Bluetooth MAC addresses. Those are the identifiers used in device
fraud, and the customers did not consent to publication.

The fix is redaction, not deletion: the repair photo is legitimate evidence of the work,
only the identifier block has to go (see `specs/006-gallery-lightbox/` FR-007).

This module is the shared engine for three callers:
  - `scan_device_identifiers.py` — sweep the whole upload tree (slow, run locally)
  - `redact_device_identifiers.py` — pixelate the offending regions in place
  - `migration/tests/test_no_device_identifiers.py` — the build-phase gate

OCR needs the `tesseract` binary (Debian/Ubuntu: `apt-get install tesseract-ocr`).
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

# Tesseract parallelises internally via OpenMP, which is actively harmful when several
# instances run at once: each grabs ~4 threads, so 3 workers oversubscribe a 4-core box
# and per-image time collapsed from 0.4s to 13-47s in testing. One thread per process,
# parallelism from the worker pool instead.
_OCR_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1"}

IMAGE_SUFFIXES = {".webp", ".jpg", ".jpeg", ".png"}

# Upscale small images before OCR. Repair photos are often phone-screen crops a couple of
# hundred pixels wide, and tesseract reads those far better at 2-3x.
MIN_OCR_WIDTH = 1000

# Per-image OCR ceiling. Nothing in this tree needs more than ~1.5s.
OCR_TIMEOUT_S = 60

# --- what counts as an identifier -------------------------------------------------
# Digit runs are normalised (spaces/dashes/slashes stripped) before length checks,
# because About screens print IMEIs as "3512 6011 2345 678".
PATTERNS = [
    ("imei_keyword", re.compile(r"\bIMEI\b", re.I)),
    ("meid_keyword", re.compile(r"\bMEID\b", re.I)),
    ("serial_keyword", re.compile(r"\b(serial\s*(number|no\.?)?|s/n)\b", re.I)),
    ("mac_keyword", re.compile(r"\b(wi-?fi|bluetooth)\s*address\b", re.I)),
    ("mac_address", re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.I)),
    # 14-16 digits covers IMEI (15), IMEISV (16) and MEID (14).
    ("long_digit_run", re.compile(r"\b\d{14,16}\b")),
    ("owner_named_device", re.compile(r"\b\w+['’]s\s+(iphone|ipad|galaxy|redmi|mac|watch)\b", re.I)),
]

# Words that make a long digit run innocuous (model/part numbers on a mainboard shot).
BENIGN_CONTEXT = re.compile(r"\b(model|part\s*no|fcc|ic\s*id)\b", re.I)


def have_tesseract() -> bool:
    return shutil.which("tesseract") is not None


def _normalise_digits(text: str) -> str:
    """Join digit groups split by spaces/dashes/slashes so a printed IMEI reads as one run."""
    return re.sub(r"(?<=\d)[\s\-/](?=\d)", "", text)


def iter_images(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
            yield p


def ocr_words(path: Path):
    """OCR one image; return (full_text, words) where each word is
    {text, left, top, width, height, conf}. Coordinates are in ORIGINAL image pixels."""
    with Image.open(path) as im:
        im = im.convert("L")
        w, h = im.size
        scale = max(1.0, MIN_OCR_WIDTH / w) if w else 1.0
        if scale > 1.0:
            im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
            im.save(tmp.name, "PNG")
            # psm 11 (sparse text) reads About-screen values well. psm 3 (the default)
            # is pathological on small images — measured at 104s for a 296x607 crop
            # versus 0.5s here — so it is not an option. The timeout is a guard against
            # one bad file stalling a 2,700-image sweep.
            try:
                proc = subprocess.run(
                    ["tesseract", tmp.name, "stdout", "--psm", "11", "tsv"],
                    capture_output=True, text=True, timeout=OCR_TIMEOUT_S,
                    env=_OCR_ENV,
                )
            except subprocess.TimeoutExpired:
                return "", []
    if proc.returncode != 0:
        return "", []

    words = []
    lines = proc.stdout.splitlines()
    for row in lines[1:]:                      # first row is the TSV header
        cols = row.split("\t")
        if len(cols) < 12:
            continue
        text = cols[11].strip()
        if not text:
            continue
        try:
            left, top, width, height = (int(cols[i]) for i in (6, 7, 8, 9))
            conf = float(cols[10])
        except ValueError:
            continue
        words.append({
            "text": text,
            "left": int(left / scale), "top": int(top / scale),
            "width": int(width / scale), "height": int(height / scale),
            "conf": conf,
        })
    return " ".join(w["text"] for w in words), words


def find_identifiers(text: str, words=None):
    """Return a list of {kind, match} for identifiers present in OCR text."""
    hits = []
    joined = _normalise_digits(text)
    for kind, rx in PATTERNS:
        for m in rx.finditer(joined):
            frag = m.group(0)
            if kind == "long_digit_run":
                window = joined[max(0, m.start() - 40):m.end() + 40]
                if BENIGN_CONTEXT.search(window):
                    continue
            hits.append({"kind": kind, "match": frag})
    return hits


def scan_image(path: Path):
    """OCR + detect. Returns None when clean, else a finding dict."""
    text, words = ocr_words(path)
    hits = find_identifiers(text, words)
    if not hits:
        return None
    return {"path": str(path), "hits": hits, "text": text[:600], "words": words}


# Office formats are zip containers that keep pictures under */media/. PDFs are
# not handled here: extracting their images needs poppler, which neither the dev
# box nor CI has — the PII gate pins the set of tracked PDFs instead, so a new
# one fails until it is reviewed by hand (spec 009, D003).
OFFICE_SUFFIXES = {".pptx", ".docx", ".xlsx"}
EMBEDDED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}


def embedded_images(doc: Path, out_dir: Path):
    """Yield (label, extracted_path) for every raster image inside an Office file.

    The PII gate used to scan static/img/uploads only, so a photo embedded in a
    tracked .pptx was invisible to it — and the committed reference deck shows
    a 'Serial number' label. Extracting the media is what lets those photos go
    through the same hash-then-OCR path as everything else.

    A document that cannot be opened raises: its contents are UNKNOWN, and
    yielding nothing would read as "scanned, clean" (CON-DATA-002).
    """
    import zipfile
    try:
        z = zipfile.ZipFile(doc)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"cannot read {doc.name} as an Office document: {exc}") from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    with z:
        for i, name in enumerate(sorted(z.namelist())):
            if "/media/" not in name or Path(name).suffix.lower() not in EMBEDDED_IMAGE_SUFFIXES:
                continue
            target = out_dir / f"{doc.stem}-{i:03d}{Path(name).suffix.lower()}"
            target.write_bytes(z.read(name))
            yield f"{doc.name}#{name}", target
