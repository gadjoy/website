"""Unit tests for device_identifiers.py — OCR and identifier detection.

This is the detection core the whole PII gate rests on: scan, redact and the
build-phase test all call it. 80% covered, and the uncovered 20% was ocr_words'
internals — the upscale, the tesseract invocation, and the TSV parse that
produces the coordinates redaction then mosaics.

Those coordinates are the dangerous part. ocr_words upscales small images before
OCR and must divide the reported positions back down; if it did not, every box
would be offset and a redaction pass would mosaic blank space beside a legible
serial. That is not hypothetical — the first batch reported 226/226 success with
a serial still readable, from wrong geometry.

tesseract is stubbed so the TSV parse is tested directly rather than through
whatever the local tesseract build happens to emit.

Order, recorded honestly (CON-PROC-005): written after the module existed. Each
guard names its mutation.
"""
import subprocess
import sys

import pytest
from PIL import Image

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "migration" / "scripts"))


@pytest.fixture(scope="module")
def di():
    import device_identifiers
    return device_identifiers


def tsv(*rows):
    """A tesseract TSV: header line, then rows of 12 columns."""
    head = "\t".join(["level", "page", "block", "par", "line", "word",
                      "left", "top", "width", "height", "conf", "text"])
    return "\n".join([head, *rows])


def row(text, left=10, top=20, width=50, height=14, conf=96.0):
    return "\t".join(["5", "1", "1", "1", "1", "1",
                      str(left), str(top), str(width), str(height), str(conf), text])


class Proc:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


@pytest.fixture
def image(tmp_path):
    def make(size=(1600, 900)):
        p = tmp_path / f"shot-{size[0]}x{size[1]}.png"
        Image.new("RGB", size, (200, 200, 200)).save(p, "PNG")
        return p
    return make


# --- have_tesseract ----------------------------------------------------------

def test_have_tesseract_reflects_the_path(di, monkeypatch):
    monkeypatch.setattr(di.shutil, "which", lambda n: "/usr/bin/tesseract")
    assert di.have_tesseract() is True
    monkeypatch.setattr(di.shutil, "which", lambda n: None)
    assert di.have_tesseract() is False


# --- _normalise_digits -------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("35 209806 885851 2", "352098068858512"),
    ("35-209806-885851-2", "352098068858512"),
    ("35/209806/885851/2", "352098068858512"),
    ("no digits here", "no digits here"),
])
def test_split_digit_runs_are_joined(di, raw, expected):
    """An IMEI printed in groups must read as one run. Mutation proving this:
    remove the lookbehind/lookahead so it strips all whitespace, and ordinary
    prose collapses into one word, which then false-positives everywhere."""
    assert di._normalise_digits(raw) == expected


def test_a_space_between_a_digit_and_a_letter_is_kept(di):
    assert di._normalise_digits("Model 5 Pro") == "Model 5 Pro"


# --- iter_images -------------------------------------------------------------

def test_iter_images_yields_only_image_suffixes(di, tmp_path):
    for n in ("a.png", "b.WEBP", "c.jpg", "notes.txt", "data.json"):
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.jpeg").write_bytes(b"x")

    assert sorted(p.name for p in di.iter_images(tmp_path)) == \
        ["a.png", "b.WEBP", "c.jpg", "d.jpeg"]


# --- find_identifiers --------------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("IMEI 352098068858512", "long_digit_run"),
    ("MAC a4:5e:60:ff:01:9b", "mac_address"),
    ("Gautam's iPhone", "owner_named_device"),
])
def test_each_identifier_shape_is_detected(di, text, kind):
    assert kind in {h["kind"] for h in di.find_identifiers(text)}


def test_a_digit_run_split_by_spaces_is_still_detected(di):
    """The printed form on an About screen. Mutation proving this: drop the
    _normalise_digits call and a spaced IMEI publishes undetected."""
    hits = di.find_identifiers("IMEI 35 209806 885851 2")

    assert any(h["kind"] == "long_digit_run" for h in hits)


@pytest.mark.parametrize("context", [
    "Model 352098068858512", "Part No 352098068858512",
    "FCC 352098068858512", "IC ID 352098068858512",
])
def test_a_digit_run_in_benign_context_is_not_flagged(di, context):
    """Mainboard shots carry model and part numbers. Mutation proving this:
    remove the BENIGN_CONTEXT check and every mainboard photo is flagged, which
    inflates the sweep until nobody reads it."""
    assert [h for h in di.find_identifiers(context) if h["kind"] == "long_digit_run"] == []


def test_benign_context_does_not_excuse_a_mac_address(di):
    """The suppression is scoped to long digit runs only."""
    hits = di.find_identifiers("Model a4:5e:60:ff:01:9b")

    assert any(h["kind"] == "mac_address" for h in hits)


def test_a_clean_screen_yields_no_hits(di):
    assert di.find_identifiers("Settings About phone Software version") == []


def test_a_short_digit_run_is_not_an_imei(di):
    assert di.find_identifiers("Order 12345") == []


# --- ocr_words: coordinates --------------------------------------------------

def test_coordinates_are_reported_in_original_pixels_after_upscaling(di, image, monkeypatch):
    """THE geometry guard. A small image is upscaled before OCR, so tesseract's
    coordinates are in upscaled pixels and must be divided back down.

    Mutation proving this: drop the `/ scale` divisions and the returned boxes
    are offset by the scale factor — redaction then mosaics empty space beside a
    fully legible serial, which is exactly what happened to 2023/05/image-4.webp.
    """
    small = image((600, 400))                       # below MIN_OCR_WIDTH -> upscaled
    scale = di.MIN_OCR_WIDTH / 600
    assert scale > 1.0, "fixture must actually trigger the upscale"

    monkeypatch.setattr(di.subprocess, "run",
                        lambda *a, **k: Proc(tsv(row("RZ8J50WTJRR", left=400, top=200,
                                                     width=160, height=40))))

    _text, words = di.ocr_words(small)

    assert words[0]["left"] == int(400 / scale)
    assert words[0]["top"] == int(200 / scale)
    assert words[0]["width"] == int(160 / scale)
    assert words[0]["height"] == int(40 / scale)


def test_a_large_image_is_not_upscaled_and_keeps_its_coordinates(di, image, monkeypatch):
    big = image((1600, 900))
    monkeypatch.setattr(di.subprocess, "run",
                        lambda *a, **k: Proc(tsv(row("IMEI", left=123, top=456))))

    _text, words = di.ocr_words(big)

    assert (words[0]["left"], words[0]["top"]) == (123, 456)


# --- ocr_words: TSV parsing --------------------------------------------------

def test_the_tsv_header_row_is_skipped(di, image, monkeypatch):
    monkeypatch.setattr(di.subprocess, "run", lambda *a, **k: Proc(tsv(row("Serial"))))

    text, words = di.ocr_words(image())

    assert [w["text"] for w in words] == ["Serial"]
    assert text == "Serial"


def test_blank_and_short_rows_are_skipped(di, image, monkeypatch):
    monkeypatch.setattr(di.subprocess, "run", lambda *a, **k: Proc(tsv(
        row("   "), "5\t1\t1\t1", row("Serial"))))

    _text, words = di.ocr_words(image())

    assert [w["text"] for w in words] == ["Serial"]


def test_a_row_with_unparseable_geometry_is_skipped_not_fatal(di, image, monkeypatch):
    """Tesseract emits '-1' confidences and occasional junk. One bad row must
    not lose the rest of the screen."""
    bad = "\t".join(["5", "1", "1", "1", "1", "1", "x", "y", "z", "w", "nope", "Junk"])
    monkeypatch.setattr(di.subprocess, "run",
                        lambda *a, **k: Proc(tsv(bad, row("RZ8J50WTJRR"))))

    _text, words = di.ocr_words(image())

    assert [w["text"] for w in words] == ["RZ8J50WTJRR"]


def test_the_joined_text_is_the_words_in_order(di, image, monkeypatch):
    monkeypatch.setattr(di.subprocess, "run", lambda *a, **k: Proc(tsv(
        row("IMEI"), row("352098068858512"))))

    text, _words = di.ocr_words(image())

    assert text == "IMEI 352098068858512"


# --- ocr_words: failure modes ------------------------------------------------

def test_a_tesseract_timeout_returns_empty_rather_than_raising(di, image, monkeypatch):
    """Mutation proving this: let TimeoutExpired propagate and one bad file ends
    a 2,700-image sweep partway, under-reporting findings."""
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="tesseract", timeout=di.OCR_TIMEOUT_S)

    monkeypatch.setattr(di.subprocess, "run", boom)

    assert di.ocr_words(image()) == ("", [])


def test_a_nonzero_tesseract_exit_returns_empty(di, image, monkeypatch):
    monkeypatch.setattr(di.subprocess, "run",
                        lambda *a, **k: Proc(tsv(row("Serial")), returncode=1))

    assert di.ocr_words(image()) == ("", [])


def test_ocr_runs_single_threaded(di, image, monkeypatch):
    """OMP_THREAD_LIMIT=1. Three concurrent tesseracts each grabbing ~4 threads
    on 4 cores took per-image time from 0.4s to 13-47s. Mutation proving this:
    pass os.environ instead of _OCR_ENV and the assertion fails."""
    seen = {}

    def capture(args, **kw):
        seen.update(kw)
        return Proc(tsv(row("Serial")))

    monkeypatch.setattr(di.subprocess, "run", capture)
    di.ocr_words(image())

    assert seen["env"]["OMP_THREAD_LIMIT"] == "1"


def test_sparse_page_segmentation_is_used(di, image, monkeypatch):
    """psm 3 was measured at 104s for a 296x607 crop versus 0.5s for psm 11."""
    seen = {}
    monkeypatch.setattr(di.subprocess, "run",
                        lambda args, **kw: seen.update(args=args) or Proc(tsv(row("x"))))

    di.ocr_words(image())

    assert "--psm" in seen["args"] and seen["args"][seen["args"].index("--psm") + 1] == "11"


# --- scan_image --------------------------------------------------------------

def test_scan_image_returns_none_for_a_clean_photo(di, image, monkeypatch):
    monkeypatch.setattr(di, "ocr_words", lambda p: ("Settings About phone", []))

    assert di.scan_image(image()) is None


def test_scan_image_reports_the_path_and_hits(di, image, monkeypatch):
    p = image()
    monkeypatch.setattr(di, "ocr_words",
                        lambda path: ("IMEI 352098068858512", [{"text": "IMEI"}]))

    found = di.scan_image(p)

    assert found["path"] == str(p)
    assert any(h["kind"] == "long_digit_run" for h in found["hits"])
    assert found["words"] == [{"text": "IMEI"}]


def test_scan_image_truncates_the_stored_text(di, image, monkeypatch):
    """The findings JSON holds thousands of entries; unbounded OCR text would
    make it unreadable, and it may itself contain identifiers."""
    monkeypatch.setattr(di, "ocr_words", lambda p: ("a4:5e:60:ff:01:9b " + "x" * 5000, []))

    assert len(di.scan_image(image())["text"]) == 600
