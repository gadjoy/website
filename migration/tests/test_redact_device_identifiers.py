"""Unit tests for redact_device_identifiers.py — the tool that obscures customer
identifiers in repair photos.

38% covered before this file. What was untested was everything that decides
whether the image on disk gets overwritten, which is the only irreversible thing
this tool does. The first redaction batch reported 226/226 success while leaving
a serial fully legible, and redaction is not idempotent for detection — OCR
cannot find an already-mosaiced label — so a wrong write cannot be found and
re-fixed later. The originals had to be restored from git.

The guards that matter are therefore the two that refuse to write:
MAX_REDACT_FRACTION and --dry-run.

Order, recorded honestly (CON-PROC-005): written after the module existed. Each
guard names the mutation that proves it.
"""
import sys

import pytest
from PIL import Image

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "migration" / "scripts"))


@pytest.fixture(scope="module")
def rd():
    import redact_device_identifiers
    return redact_device_identifiers


@pytest.fixture
def photo(tmp_path):
    """A 200x200 PNG with high-frequency detail, so mosaicking is measurable."""
    im = Image.new("RGB", (200, 200))
    im.putdata([(x * 7 % 256, y * 11 % 256, (x + y) % 256)
                for y in range(200) for x in range(200)])
    p = tmp_path / "about.png"
    im.save(p, "PNG")
    return p


def run(rd, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["redact_device_identifiers.py", *argv])
    return rd.main()


# --- parse_box ---------------------------------------------------------------

def test_parse_box_converts_xywh_to_corners(rd):
    assert rd.parse_box("10,20,30,40") == (10, 20, 40, 60)


def test_parse_box_scales_a_fractional_spec_by_the_image_size(rd):
    assert rd.parse_box("0.5,0.25,0.5,0.5", size=(200, 400), fractional=True) == \
        (100.0, 100.0, 200.0, 300.0)


@pytest.mark.parametrize("spec", ["1,2,3", "1,2,3,4,5"])
def test_parse_box_rejects_a_wrong_arity(rd, spec):
    with pytest.raises(ValueError, match="expected x,y,w,h"):
        rd.parse_box(spec)


def test_parse_box_rejects_unparseable_numbers(rd):
    """An empty or non-numeric spec fails in float() before the arity check, so
    the message differs. Both are ValueError; neither silently yields a box."""
    for spec in ("", "a,b,c,d"):
        with pytest.raises(ValueError):
            rd.parse_box(spec)


def test_fractional_box_without_a_size_is_an_error_not_a_silent_zero(rd):
    """CON-VER-005: 'cannot compute' must not be reported as a box at the origin,
    which would mosaic the wrong corner and leave the identifier visible."""
    with pytest.raises(ValueError, match="fractional box needs image size"):
        rd.parse_box("0.1,0.1,0.1,0.1", fractional=True)


# --- mosaic ------------------------------------------------------------------

def adjacent_energy(region):
    """Mean absolute difference between horizontally adjacent pixels.

    Counting distinct colours does NOT work here: mosaic() downsamples to at
    most 5x5 blocks and then Gaussian-blurs the upscale, which re-interpolates
    thousands of smooth intermediate values. The colour count barely moves
    (3600 -> 3298 measured) while the legible structure is entirely gone. What
    actually collapses is high-frequency energy, so that is what is measured.
    """
    px = list(region.getdata())
    w = region.size[0]
    rows = [px[i:i + w] for i in range(0, len(px), w)]
    diffs = [abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
             for row in rows for a, b in zip(row, row[1:])]
    return sum(diffs) / max(1, len(diffs))


def test_mosaic_destroys_detail_inside_the_box(rd):
    """A 1px checkerboard stands in for text: maximal adjacent contrast, which
    is what makes a serial number readable. The gradient fixture used elsewhere
    is too gentle to demonstrate anything (16.2 -> 3.7); this is 765 -> near
    zero, measured rather than assumed."""
    im = Image.new("RGB", (120, 120))
    im.putdata([(255, 255, 255) if (x + y) % 2 else (0, 0, 0)
                for y in range(120) for x in range(120)])
    before = adjacent_energy(im.crop((20, 20, 100, 100)))

    out = rd.mosaic(im, (20, 20, 100, 100))
    after = adjacent_energy(out.crop((20, 20, 100, 100)))

    assert before > 700, f"fixture must be high-contrast, got {before:.1f}"
    assert after < before / 50, (
        f"text-scale detail must be destroyed: {before:.1f} -> {after:.1f}")


def test_mosaic_leaves_pixels_outside_the_box_untouched(rd, photo):
    with Image.open(photo) as src:
        im = src.convert("RGB")
    outside_before = list(im.crop((100, 100, 200, 200)).getdata())

    out = rd.mosaic(im, (0, 0, 50, 50))

    assert list(out.crop((100, 100, 200, 200)).getdata()) == outside_before


@pytest.mark.parametrize("box", [(50, 50, 50, 80), (50, 50, 80, 50), (80, 80, 20, 20)])
def test_a_degenerate_box_is_a_noop(rd, photo, box):
    with Image.open(photo) as src:
        im = src.convert("RGB")
    before = list(im.getdata())

    assert list(rd.mosaic(im, box).getdata()) == before


def test_mosaic_clamps_a_box_that_runs_past_the_frame(rd, photo):
    """An out-of-bounds box must be clipped, not crash — auto_boxes deliberately
    emits boxes that run to the right edge and beyond."""
    with Image.open(photo) as src:
        im = src.convert("RGB")

    out = rd.mosaic(im, (-50, -50, 10_000, 10_000))

    assert out.size == (200, 200)


# --- auto_boxes --------------------------------------------------------------

def word(text, left, top, width=60, height=12):
    return {"text": text, "left": left, "top": top, "width": width, "height": height}


def test_a_label_band_runs_to_the_right_edge(rd, photo, monkeypatch):
    """The two-column fix. Mutation proving this: replace `width` with
    `lb["left"] + lb["width"]` and the band covers only the label, leaving a
    same-row value untouched — which is exactly how 2023/05/image-4.webp kept a
    fully legible serial through a redaction pass."""
    monkeypatch.setattr(rd, "ocr_words", lambda p: ("", [word("Serial", 10, 30)]))

    boxes = rd.auto_boxes(photo)

    assert any(right == 200 for _, _, right, _ in boxes), \
        "a label band must extend to the right edge of the frame"


def test_a_label_band_is_tall_enough_to_cover_the_following_line(rd, photo, monkeypatch):
    """Mutation proving this: drop the multiplier from 3.0 to 1.0 and the band
    stops above the digits on a label-above-value layout."""
    monkeypatch.setattr(rd, "ocr_words", lambda p: ("", [word("IMEI", 10, 30, height=12)]))

    bands = [b for b in rd.auto_boxes(photo) if b[2] == 200]

    assert bands, "expected a label band"
    top, bottom = bands[0][1], bands[0][3]
    assert bottom - top >= 36, "the band must span the label row and the value row"


def test_an_identifier_value_gets_its_own_box(rd, photo, monkeypatch):
    monkeypatch.setattr(rd, "ocr_words",
                        lambda p: ("", [word("RZ8J50WTJRR", 40, 90)]))

    assert rd.auto_boxes(photo), "a bare identifier value must be boxed even with no label"


def test_short_ordinary_words_are_not_boxed(rd, photo, monkeypatch):
    monkeypatch.setattr(rd, "ocr_words", lambda p: (
        "", [word("About", 10, 30), word("phone", 10, 50), word("Version", 10, 70)]))

    assert rd.auto_boxes(photo) == []


def test_any_eight_letter_word_is_boxed_as_an_identifier(rd, photo, monkeypatch):
    """CHARACTERIZATION TEST — an over-matching regex, recorded not fixed.

    VALUE_RE's final alternative is [A-Z0-9]{8,} compiled with re.I, so it
    matches any word of eight or more letters: "Settings", "Software",
    "Bluetooth" are all treated as identifier values. Verified, not inferred.

    Over-redaction is the safe direction for privacy, which is why this has not
    caused a leak. The cost is the opposite failure: every spurious box inflates
    the measured frame fraction, and past MAX_REDACT_FRACTION the tool REFUSES
    an image it should have redacted, sending a real About screen back for
    manual review. Narrowing the alternative (requiring at least one digit, say)
    is a change to detection behaviour and belongs in its own change, with a
    re-sweep to confirm nothing stops being detected.
    """
    monkeypatch.setattr(rd, "ocr_words", lambda p: ("", [word("Settings", 10, 10)]))

    assert rd.auto_boxes(photo), (
        "if this is now empty, VALUE_RE was narrowed — re-run the full OCR sweep "
        "and confirm no real identifier stopped being detected"
    )


# --- main: the two refusals --------------------------------------------------

def test_over_redaction_refuses_and_leaves_the_file_untouched(rd, photo, monkeypatch, capsys):
    """THE guard. Mutation proving this: change the comparison to
    `fraction > 1.0` and a box covering most of the frame is written.

    Past MAX_REDACT_FRACTION the photo has stopped being evidence of a repair,
    and because redaction is not reversible or re-detectable, writing it is
    unrecoverable without git. Exit code 2 is distinct from the 1 used for
    "nothing to redact" so a caller can tell the two apart."""
    before = photo.read_bytes()

    rc = run(rd, monkeypatch, str(photo), "--box", "0,0,150,150")

    assert rc == 2
    assert "REFUSED" in capsys.readouterr().out
    assert photo.read_bytes() == before, "a refused redaction must not write"


def test_a_box_just_under_the_cap_is_written(rd, photo, monkeypatch, capsys):
    """Proves the refusal above is a boundary, not a blanket refusal."""
    before = photo.read_bytes()

    rc = run(rd, monkeypatch, str(photo), "--box", "0,0,90,90")

    assert rc == 0
    assert "written in place" in capsys.readouterr().out
    assert photo.read_bytes() != before


def test_dry_run_reports_without_writing(rd, photo, monkeypatch, capsys):
    """Mutation proving this: remove the `if args.dry_run: return 0` and a
    rehearsal overwrites the photo it was meant to only inspect."""
    before = photo.read_bytes()

    rc = run(rd, monkeypatch, str(photo), "--box", "0,0,50,50", "--dry-run")

    assert rc == 0
    assert photo.read_bytes() == before, "--dry-run must never write"
    assert "region(s)" in capsys.readouterr().out


def test_no_regions_is_reported_as_failure_not_success(rd, photo, monkeypatch, capsys):
    """Mutation proving this: return 0 instead of 1 and a batch run reports
    success for an image it never touched — which is how 226/226 was reported
    while a serial stayed legible."""
    before = photo.read_bytes()

    rc = run(rd, monkeypatch, str(photo))

    assert rc == 1
    assert "no regions to redact" in capsys.readouterr().out
    assert photo.read_bytes() == before


# --- main: geometry and format ----------------------------------------------

def test_boxes_are_clamped_to_the_frame_before_measuring(rd, photo, monkeypatch, capsys):
    """A box running past the edge must be measured at its clipped size, or the
    fraction is overstated and a legitimate redaction is refused."""
    rc = run(rd, monkeypatch, str(photo), "--box", "180,180,1000,1000")

    out = capsys.readouterr().out
    assert rc == 0
    assert "(180, 180, 200, 200)" in out


def test_a_fully_out_of_frame_box_rewrites_the_file_for_nothing(rd, photo, monkeypatch, capsys):
    """CHARACTERIZATION TEST — a real defect, recorded not fixed.

    `if not boxes: return 1` is evaluated BEFORE the clamping loop, so a box
    entirely outside the frame survives that check, clamps away to nothing, and
    the function falls through to `im.save(path, fmt)`. The result: "0 region(s),
    0.0% of frame" followed by "written in place", exit code 0.

    Two costs. The file is re-encoded for no reason, which is lossy for WEBP and
    JPEG — the uploads tree is WEBP. And the run reports success having redacted
    nothing, the same shape as the batch that reported 226/226 while leaving a
    serial legible.

    The fix is to re-check emptiness after clamping. That changes an exit code,
    so it belongs in its own change rather than a coverage PR.
    """
    rc = run(rd, monkeypatch, str(photo), "--box", "500,500,10,10")
    out = capsys.readouterr().out

    assert rc == 0, "if this is now 1, the post-clamp check was added — update this test"
    assert "0 region(s)" in out
    assert "written in place" in out, "documents the needless re-encode"


def test_the_image_format_is_preserved_on_write(rd, tmp_path, monkeypatch):
    """Mutation proving this: save as PNG unconditionally and a .webp in the
    uploads tree becomes a PNG under its old name — the build-phase gate then
    reads a file whose bytes do not match its extension."""
    im = Image.new("RGB", (100, 100), (120, 30, 200))
    p = tmp_path / "shot.webp"
    im.save(p, "WEBP")

    assert run(rd, monkeypatch, str(p), "--box", "0,0,40,40") == 0

    with Image.open(p) as out:
        assert out.format == "WEBP"


def test_fractional_regions_are_accepted(rd, photo, monkeypatch, capsys):
    rc = run(rd, monkeypatch, str(photo), "--frac", "0.0,0.0,0.4,0.4")

    assert rc == 0
    assert "(0, 0, 80, 80)" in capsys.readouterr().out
