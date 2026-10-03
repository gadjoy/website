"""The visual threshold, proven in both directions (spec 012, SC-002 / SC-003).

A threshold demonstrated only where it passes might as well be infinity, and
one demonstrated only where it fails might as well be zero. Both are useless as
a merge gate: the first never catches a regression, the second is disabled
within a week.

These use synthetic images rather than site screenshots on purpose — a
controlled 10px shift is reproducible, where "the real page, moved a bit" is
not. The machinery under test is identical either way.
"""
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual import CHANNEL_TOLERANCE, MAX_DIFF_RATIO, compare  # noqa: E402

W, H = 800, 600


def page(tmp_path, name, *, offset=0, blur=0.0, text_shift=0):
    """A page-ish image: header bar, a card, and some text-like rules."""
    im = Image.new("RGB", (W, H), (250, 250, 250))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 72], fill=(32, 32, 32))                 # header
    d.rectangle([40, 120 + offset, 360, 320 + offset], fill=(220, 220, 220),
                outline=(90, 90, 90), width=2)                     # card
    # "Text" as dashed word-blocks, not continuous rules. This matters: a long
    # uniform horizontal line shifted HORIZONTALLY overlaps itself almost
    # perfectly, so only its two end caps change and a pixel diff sees nearly
    # nothing. Real glyphs have vertical edges every few pixels. A rules-based
    # fixture made test_text_moving_sideways_fails pass when it should fail —
    # the fixture was wrong, not the threshold.
    for i in range(10):
        y = 150 + offset + i * 16
        for word_x in range(60, 320, 34):
            d.rectangle([word_x + text_shift, y, word_x + 24 + text_shift, y + 8],
                        fill=(70, 70, 70))
    d.rectangle([420, 120, 760, 320], fill=(235, 235, 235))        # second card
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    p = tmp_path / f"{name}.png"
    im.save(p, "PNG")
    return p


# --- SC-003: noise alone must not fail --------------------------------------

def test_an_identical_render_passes(tmp_path):
    a = page(tmp_path, "a")
    b = page(tmp_path, "b")

    r = compare(a, b)

    assert r.ok, r.reason
    assert r.ratio == 0.0


def test_antialiasing_scale_noise_passes(tmp_path):
    """A sub-tolerance perturbation on every pixel — the shape of a machine
    rendering the same glyphs slightly differently — must be absorbed."""
    a = page(tmp_path, "a")
    with Image.open(a) as src:
        im = src.convert("RGB")
    # +/- a few levels everywhere, below CHANNEL_TOLERANCE.
    noisy = im.point(lambda v: min(255, v + CHANNEL_TOLERANCE // 4))
    b = tmp_path / "noisy.png"
    noisy.save(b, "PNG")

    r = compare(a, b)

    assert r.ok, f"antialiasing-scale noise must not fail the gate: {r.reason}"


def test_a_faint_edge_softening_passes(tmp_path):
    """A very slight blur stands in for subpixel text rendering differences."""
    a = page(tmp_path, "a")
    b = page(tmp_path, "b", blur=0.3)

    r = compare(a, b)

    assert r.ok, r.reason


# --- SC-002: a real layout move must fail -----------------------------------

def test_a_ten_pixel_shift_fails(tmp_path):
    """The headline criterion. Mutation proving the threshold is doing work:
    raise MAX_DIFF_RATIO to 1.0 and this goes green."""
    a = page(tmp_path, "a")
    b = page(tmp_path, "b", offset=10)

    r = compare(a, b)

    assert not r.ok, f"a 10px element shift must fail, got {r.reason}"
    assert r.ratio > MAX_DIFF_RATIO


def test_even_a_two_pixel_shift_fails(tmp_path):
    """Headroom check: the gate is not only sensitive at exactly 10px."""
    a = page(tmp_path, "a")
    b = page(tmp_path, "b", offset=2)

    assert not compare(a, b).ok


def test_text_moving_sideways_fails(tmp_path):
    a = page(tmp_path, "a")
    b = page(tmp_path, "b", text_shift=6)

    assert not compare(a, b).ok


def test_known_limit_a_shifted_horizontal_rule_is_nearly_invisible(tmp_path):
    """CHARACTERIZATION TEST — a genuine limit of pixel diffing, recorded.

    Translating a long uniform horizontal rule along its own axis changes only
    its end caps, so the changed-pixel ratio stays far below any usable budget.
    This is a property of the technique, not a tuning mistake: lowering the
    budget enough to catch it would make every antialiasing difference fail.

    It is recorded so nobody later reads "visual regression testing" as "any
    visual change is caught". Element MOVEMENT in the layout is caught
    (test_a_two_pixel_shift_fails); a divider sliding along its own length is
    not. If that matters for a specific element, assert its geometry directly
    in a journey test instead.
    """
    im_a = Image.new("RGB", (W, H), (250, 250, 250))
    ImageDraw.Draw(im_a).line([40, 300, 760, 300], fill=(0, 0, 0), width=2)
    a = tmp_path / "rule_a.png"
    im_a.save(a, "PNG")

    im_b = Image.new("RGB", (W, H), (250, 250, 250))
    ImageDraw.Draw(im_b).line([46, 300, 766, 300], fill=(0, 0, 0), width=2)
    b = tmp_path / "rule_b.png"
    im_b.save(b, "PNG")

    r = compare(a, b)

    assert r.ok, "if this now fails, the budget was tightened — re-check SC-003"
    assert r.ratio < MAX_DIFF_RATIO


def test_a_changed_viewport_size_is_reported_distinctly(tmp_path):
    """'The image is a different size' must not be reported as 'these pixels
    differ' — it is a different failure with a different cause (CON-VER-005)."""
    a = page(tmp_path, "a")
    with Image.open(a) as src:
        src.convert("RGB").resize((W, H + 40)).save(tmp_path / "tall.png", "PNG")

    r = compare(a, tmp_path / "tall.png")

    assert not r.ok
    assert r.size_changed
    assert "size changed" in r.reason


def test_a_blue_only_change_is_not_scaled_away(tmp_path):
    """Why max_channel exists instead of convert("L").

    Luminance weighting scales blue to ~11%, so a blue-channel-only change of
    200 levels would register as ~22 and slip under the tolerance. Mutation
    proving this: replace max_channel with .convert("L") and this fails.
    """
    a = page(tmp_path, "a")
    with Image.open(a) as src:
        im = src.convert("RGB")
    r_, g_, b_ = im.split()
    b_ = b_.point(lambda v: max(0, v - 200))
    Image.merge("RGB", (r_, g_, b_)).save(tmp_path / "blue.png", "PNG")

    assert not compare(a, tmp_path / "blue.png").ok


def test_a_diff_image_is_written_only_on_failure(tmp_path):
    a = page(tmp_path, "a")
    same = page(tmp_path, "same")
    moved = page(tmp_path, "moved", offset=10)

    out_pass = tmp_path / "diffs" / "pass.png"
    out_fail = tmp_path / "diffs" / "fail.png"
    compare(a, same, diff_out=out_pass)
    compare(a, moved, diff_out=out_fail)

    assert not out_pass.exists(), "no diff artifact for a passing comparison"
    assert out_fail.exists(), "a failing comparison must leave a diff to look at"
