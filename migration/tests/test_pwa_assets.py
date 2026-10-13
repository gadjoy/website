"""PWA icons and manifest (spec 013, FR-001..FR-003; SC-001, SC-002).

Written BEFORE the assets exist (Principle I). Expected red until Phase A and B
land, and the failure messages are written to say what is missing rather than
just asserting False.

Why icons get their own tests: Chrome refuses installability on a non-square
icon, and the brand logo is 512x497 — close enough to look fine and wrong enough
to fail silently at the one moment it matters. And a "maskable" icon that is
really the standard icon relabelled gets its edges cropped off on Android, which
nobody notices until someone installs it.
"""
import json
import sys

import pytest
from PIL import Image

from conftest import REPO_ROOT

ICON_DIR = REPO_ROOT / "static" / "img" / "pwa"
# Hugo resolves the home page for a custom output format from layouts/index.<suffix>.
MANIFEST_TMPL = REPO_ROOT / "layouts" / "index.webmanifest"

STANDARD = {192: ICON_DIR / "icon-192.png", 512: ICON_DIR / "icon-512.png"}
MASKABLE = {192: ICON_DIR / "maskable-192.png", 512: ICON_DIR / "maskable-512.png"}


def content_box(im):
    """Bounding box of the MARK, i.e. pixels that differ from the background.

    Not Image.getbbox(): these canvases are fully opaque, so getbbox() returns
    the whole image every time and any comparison between two icons passes
    trivially. That is how this test was first written, and it would have been
    the seventh vacuous guard in this repo.
    """
    from PIL import ImageChops
    rgb = im.convert("RGB")
    bg = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    diff = ImageChops.difference(rgb, bg).convert("L")
    return diff.point(lambda v: 255 if v > 16 else 0).getbbox()


# --- icons -------------------------------------------------------------------

@pytest.mark.parametrize("size", sorted(STANDARD))
def test_a_standard_icon_exists_at_each_required_size(size):
    p = STANDARD[size]
    assert p.is_file(), f"{p.relative_to(REPO_ROOT)} missing — run tools/make_pwa_icons.py"
    with Image.open(p) as im:
        assert im.size == (size, size), (
            f"{p.name} is {im.size}, must be exactly ({size}, {size}). Chrome refuses "
            f"installability on a non-square icon, and the source logo is 512x497.")


@pytest.mark.parametrize("size", sorted(MASKABLE))
def test_a_maskable_icon_exists_at_each_required_size(size):
    p = MASKABLE[size]
    assert p.is_file(), f"{p.relative_to(REPO_ROOT)} missing"
    with Image.open(p) as im:
        assert im.size == (size, size)


@pytest.mark.parametrize("size", sorted(STANDARD))
def test_the_maskable_icon_is_not_just_the_standard_one_renamed(size):
    """Android crops a maskable icon to a circle, clipping roughly 10% off each
    edge. Relabelling the standard icon leaves the mark's edges sliced off — the
    commonest way to ship a broken install icon.

    The maskable variant must therefore have MORE padding, which makes its
    non-background content strictly smaller.
    """
    with Image.open(STANDARD[size]) as a, Image.open(MASKABLE[size]) as b:
        assert a.tobytes() != b.tobytes(), (
            f"maskable-{size}.png is byte-identical to icon-{size}.png — it needs "
            f"its own safe-zone padding, not a copy")

        ab, bb = content_box(a), content_box(b)
        assert ab and bb, "an icon appears to be a blank canvas with no mark on it"
        a_area = (ab[2] - ab[0]) * (ab[3] - ab[1])
        b_area = (bb[2] - bb[0]) * (bb[3] - bb[1])
        assert b_area < a_area, (
            f"the maskable icon's mark ({b_area}px) is not inset relative to the "
            f"standard icon's ({a_area}px); it will be cropped on Android")


def test_icons_have_an_alpha_channel_or_an_opaque_background():
    """A maskable icon must fill its whole canvas — a transparent background
    shows the launcher's colour through the crop."""
    with Image.open(MASKABLE[512]) as im:
        rgba = im.convert("RGBA")
        corners = [rgba.getpixel(xy) for xy in
                   ((0, 0), (511, 0), (0, 511), (511, 511))]
        assert all(px[3] == 255 for px in corners), (
            "maskable icon corners are transparent; it must be fully opaque so the "
            "launcher does not show through the circular crop")


# --- manifest ----------------------------------------------------------------

def test_the_manifest_is_generated_by_hugo_not_hand_written():
    """Principle X: public-facing values trace to a source. A hand-written
    static manifest drifts from hugo.yaml the first time the phone number
    changes."""
    assert MANIFEST_TMPL.is_file(), (
        f"{MANIFEST_TMPL.relative_to(REPO_ROOT)} missing — the manifest must be a "
        f"Hugo template reading hugo.yaml, not a static file")
    body = MANIFEST_TMPL.read_text()
    assert ".Site.Title" in body or ".Site.Params" in body, (
        "the manifest template hard-codes its values instead of reading hugo.yaml")


def test_no_hand_written_manifest_shadows_the_generated_one():
    for stray in ("manifest.json", "manifest.webmanifest", "site.webmanifest"):
        assert not (REPO_ROOT / "static" / stray).exists(), (
            f"static/{stray} would be served alongside the generated manifest")


# --- the icon generator (spec 013, A-1/A-2) ---------------------------------

def test_render_pads_to_a_square_without_stretching():
    """The source logo is 512x497. Padding preserves the mark's proportions;
    resizing to a square would squash it by ~3% — invisible in review and wrong
    in every launcher.

    Mutation proving this: replace thumbnail() with resize((size, size)) and the
    aspect-ratio assertion fails.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    src = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    # A mark with a known 2:1 aspect ratio.
    for x in range(400):
        for y in range(200):
            if 50 <= x < 350 and 50 <= y < 200:
                src.putpixel((x, y), (0, 0, 0, 255))

    out = mk.render(src, 512, 0.88)

    assert out.size == (512, 512)
    box = content_box(out)
    w, h = box[2] - box[0], box[3] - box[1]
    assert abs((w / h) - 2.0) < 0.05, (
        f"the mark's aspect ratio became {w / h:.2f}; padding must not stretch it")


def test_render_fills_the_canvas_opaquely():
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    out = mk.render(Image.new("RGBA", (100, 100), (0, 0, 0, 255)), 192, 0.5)

    assert out.mode == "RGB", "icons must be opaque; RGBA lets the launcher show through"
    assert out.getpixel((0, 0)) == mk.BACKGROUND


def test_a_smaller_fill_yields_a_smaller_mark():
    """The one property that makes the maskable icon different from the
    standard one. If fill stopped affecting the output, both families would be
    identical and Android would crop the mark."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    src = Image.new("RGBA", (200, 200), (0, 0, 0, 255))
    big = content_box(mk.render(src, 512, 0.88))
    small = content_box(mk.render(src, 512, 0.60))

    assert (small[2] - small[0]) < (big[2] - big[0])


def test_check_mode_reports_the_committed_icons_without_writing(tmp_path, monkeypatch):
    """--check must not rewrite the icons. A verification mode that mutates what
    it verifies is worse than none."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    before = {p: p.read_bytes() for p in ICON_DIR.glob("*.png")}
    monkeypatch.setattr(sys, "argv", ["make_pwa_icons.py", "--check"])

    assert mk.main() == 0
    assert {p: p.read_bytes() for p in ICON_DIR.glob("*.png")} == before


def test_check_mode_fails_when_an_icon_is_missing(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    monkeypatch.setattr(mk, "OUT_DIR", tmp_path / "empty")
    monkeypatch.setattr(sys, "argv", ["make_pwa_icons.py", "--check"])

    assert mk.main() == 1
    assert "missing" in capsys.readouterr().err


def test_the_committed_icons_match_what_the_script_produces():
    """Otherwise the icons and their generator drift, and nobody can tell which
    is authoritative."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    with Image.open(mk.SOURCE) as src:
        source = src.convert("RGBA")

    for size in mk.SIZES:
        for name, fill in (("icon", mk.STANDARD_FILL), ("maskable", mk.MASKABLE_FILL)):
            expected = mk.render(source, size, fill)
            with Image.open(ICON_DIR / f"{name}-{size}.png") as committed:
                assert committed.convert("RGB").tobytes() == expected.tobytes(), (
                    f"{name}-{size}.png differs from what make_pwa_icons.py produces — "
                    f"re-run it and commit the result")


def test_a_missing_source_logo_exits_rather_than_writing_blanks(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    monkeypatch.setattr(mk, "SOURCE", tmp_path / "nope.png")
    monkeypatch.setattr(sys, "argv", ["make_pwa_icons.py"])

    with pytest.raises(SystemExit) as exc:
        mk.main()
    assert "source logo not found" in str(exc.value)


def test_write_mode_produces_all_four_icons(tmp_path, monkeypatch, capsys):
    """The write path, exercised against a temp directory so the committed
    icons are never touched by a test run."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    out = tmp_path / "pwa"
    monkeypatch.setattr(mk, "OUT_DIR", out)
    monkeypatch.setattr(sys, "argv", ["make_pwa_icons.py"])

    assert mk.main() == 0

    produced = sorted(p.name for p in out.glob("*.png"))
    assert produced == ["icon-192.png", "icon-512.png",
                        "maskable-192.png", "maskable-512.png"]
    for name, size in (("icon-192.png", 192), ("maskable-512.png", 512)):
        with Image.open(out / name) as im:
            assert im.size == (size, size)
    assert "icons written" in capsys.readouterr().out


def test_write_mode_creates_the_output_directory(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import make_pwa_icons as mk

    out = tmp_path / "does" / "not" / "exist"
    monkeypatch.setattr(mk, "OUT_DIR", out)
    monkeypatch.setattr(sys, "argv", ["make_pwa_icons.py"])

    assert mk.main() == 0
    assert out.is_dir()
