"""Unit tests for optimize_media.py — prune, WebP conversion and reference rewriting.

0% covered before this file, and not dead code: README.md documents it as the
media step to run after a re-migration, and specs/008-media-optimization/spec.md
carries SC-006 — "optimize_media.py is idempotent, a second run changes nothing"
— with status **OWED**. These tests pay that down (see test_second_run_is_a_noop).

Portability: cwebp and sips are absent on Linux and on CI, so subprocess.run is
stubbed. That is not a convenience — step 2 deletes the source image once cwebp
reports success, so a test that shelled out for real would need the binary to
decide whether a file gets unlinked. The stub makes the delete/keep decision the
thing under test.

Order, recorded honestly (CON-PROC-005): written after the module existed. Guards
were proven by mutation; each test names its mutation.

Read test_prune_removes_every_upload_when_nothing_is_referenced before changing
this module — it documents a live data-loss path, deliberately, as a
characterization test rather than an endorsement.
"""
import sys
from pathlib import Path

import pytest

om = pytest.importorskip("optimize_media")


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A miniature site: content/, layouts/, data/, hugo.yaml and an uploads tree."""
    root = tmp_path / "site"
    (root / "content").mkdir(parents=True)
    (root / "layouts").mkdir()
    (root / "data").mkdir()
    uploads = root / "static" / "img" / "uploads" / "2025" / "02"
    uploads.mkdir(parents=True)

    monkeypatch.setattr(om, "ROOT", root)
    monkeypatch.setattr(om, "UPLOADS", root / "static" / "img" / "uploads")
    monkeypatch.setattr(om, "EXTRA", [root / "hugo.yaml"])
    return root, uploads


# --- rel_of ------------------------------------------------------------------

@pytest.mark.parametrize("ref,expected", [
    ("/img/uploads/2025/02/phone.png", "2025/02/phone.png"),
    ("img/uploads/2025/02/phone.png", "2025/02/phone.png"),          # hero: no leading slash
    ("/img/uploads/deep/er/still/x.jpeg", "deep/er/still/x.jpeg"),
])
def test_rel_of_strips_the_prefix_either_way(ref, expected):
    assert om.rel_of(ref) == expected


# --- REF_RE ------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ('![alt](/img/uploads/2025/02/a.png)', ["/img/uploads/2025/02/a.png"]),
    ('<img src="/img/uploads/2025/02/b.jpg">', ["/img/uploads/2025/02/b.jpg"]),
    ("banner: img/uploads/2025/02/c.jpeg", ["img/uploads/2025/02/c.jpeg"]),
    ('<video src="/img/uploads/2023/07/d.mp4"></video>', ["/img/uploads/2023/07/d.mp4"]),
])
def test_ref_re_finds_references_in_each_shape_the_site_uses(text, expected):
    assert om.REF_RE.findall(text) == expected


def test_ref_re_stops_at_the_closing_delimiter():
    """Dropping ')' from the excluded class must break this.

    The first input below does NOT discriminate: the trailing `\\.[A-Za-z0-9]+`
    anchor already refuses to end a match on ')', so the paren is excluded even
    when the character class permits it. Asserting only that case produced a
    vacuous test — it passed with ')' removed from the class, and the mutation
    run is what exposed it.

    The second input is the one that bites. With ')' excluded the match stops at
    the paren; with it permitted the greedy class runs on to the later '.png'
    and swallows the whole thing, so rel_of yields a path that is not on disk —
    the real file then reads as unreferenced and gets PRUNED.
    """
    assert om.REF_RE.findall('![x](/img/uploads/a.png) and text') == ["/img/uploads/a.png"]
    assert om.REF_RE.findall('![x](/img/uploads/a.png)more.png') == ["/img/uploads/a.png"]


def test_ref_re_requires_an_extension():
    assert om.REF_RE.findall("/img/uploads/2025/02/no-extension") == []


# --- SUB_RE ------------------------------------------------------------------

def test_sub_re_swaps_only_the_final_extension():
    """Double extensions are real here: "foo.jpg.png" on disk becomes
    "foo.jpg.webp". Mutation proving this: make the path group non-greedy and
    the rewrite produces "foo.webp.png", pointing at a file that never exists."""
    out = om.SUB_RE.sub(lambda m: m.group(1) + ".webp", "/img/uploads/2025/02/foo.jpg.png")
    assert out == "/img/uploads/2025/02/foo.jpg.webp"


@pytest.mark.parametrize("src", [
    "/img/uploads/a.PNG", "/img/uploads/a.JPG", "/img/uploads/a.Jpeg",
])
def test_sub_re_is_case_insensitive(src):
    assert om.SUB_RE.sub(lambda m: m.group(1) + ".webp", src).endswith(".webp")


def test_sub_re_leaves_non_convertible_media_alone():
    for keep in ("/img/uploads/clip.mp4", "/img/uploads/already.webp", "/img/uploads/a.gif"):
        assert om.SUB_RE.sub(lambda m: m.group(1) + ".webp", keep) == keep


# --- src_files ---------------------------------------------------------------

def test_src_files_collects_known_suffixes_and_hugo_yaml(site):
    root, _ = site
    (root / "content" / "post.md").write_text("x")
    (root / "layouts" / "page.html").write_text("x")
    (root / "data" / "d.json").write_text("{}")
    (root / "hugo.yaml").write_text("x")
    (root / "content" / "ignored.txt").write_text("x")
    (root / "content" / "photo.png").write_bytes(b"x")

    names = sorted(p.name for p in om.src_files())

    assert names == ["d.json", "hugo.yaml", "page.html", "post.md"]


def test_src_files_tolerates_a_missing_hugo_yaml(site):
    root, _ = site
    (root / "content" / "post.md").write_text("x")
    assert [p.name for p in om.src_files()] == ["post.md"]


# --- img_width ---------------------------------------------------------------

def test_img_width_parses_sips_output(monkeypatch):
    monkeypatch.setattr(om.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "  pixelWidth: 2400\n"})())
    assert om.img_width(Path("/x.png")) == 2400


def test_img_width_returns_zero_when_sips_says_nothing(monkeypatch):
    """Zero means "do not resize", which is the safe direction: an unparsed width
    must never be read as "small enough" OR trigger an upscale."""
    monkeypatch.setattr(om.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "command not found"})())
    assert om.img_width(Path("/x.png")) == 0


# --- prune -------------------------------------------------------------------

@pytest.fixture
def stub_tools(monkeypatch):
    """cwebp succeeds by creating its output; ffmpeg/sips do nothing."""
    def fake_run(args, *a, **k):
        if args[0] == "cwebp":
            Path(args[-1]).write_bytes(b"webp-bytes")
        return type("R", (), {"returncode": 0, "stdout": ""})()
    monkeypatch.setattr(om.subprocess, "run", fake_run)
    monkeypatch.setattr(om, "img_width", lambda p: 800)


def test_prune_removes_unreferenced_and_keeps_referenced(site, stub_tools, capsys):
    """Mutation proving this: invert the `not in keep` condition and the test
    fails on both files — the referenced image is deleted and the orphan kept."""
    root, uploads = site
    (root / "content" / "post.md").write_text("![x](/img/uploads/2025/02/used.png)")
    (uploads / "used.png").write_bytes(b"png")
    (uploads / "orphan.png").write_bytes(b"png")

    om.main()

    assert not (uploads / "orphan.png").exists(), "unreferenced file must be pruned"
    assert (uploads / "used.webp").exists(), "referenced file must survive as webp"


def test_prune_removes_every_upload_when_nothing_is_referenced(site, stub_tools):
    """CHARACTERIZATION TEST — this documents current behaviour, it does not
    endorse it.

    With no source file referencing anything, `keep` is empty and step 1 deletes
    the entire uploads tree. The reference scan swallows every read error with
    `except Exception: pass`, so a tree that merely failed to be *read* is
    indistinguishable here from a tree that is genuinely unreferenced.

    CON-PROC-006 wants a destructive action constrained by construction — a floor
    on how much may be pruned, say — rather than by the ref-scan happening to be
    correct. There is no such floor today. This test exists so that adding one
    is a visible, deliberate change rather than a silent one, and so the risk is
    recorded rather than rediscovered after an incident.
    """
    root, uploads = site
    (root / "content" / "post.md").write_text("no image references at all")
    for n in ("a.png", "b.png", "c.png"):
        (uploads / n).write_bytes(b"png")

    om.main()

    survivors = [p for p in uploads.rglob("*") if p.is_file()]
    assert survivors == [], (
        "documents the wipe path: an empty ref set prunes everything. If this "
        "test fails, a guard was added — update it and spec 008 together."
    )


# --- conversion + rewrite ----------------------------------------------------

def test_successful_conversion_rewrites_the_reference(site, stub_tools):
    root, uploads = site
    post = root / "content" / "post.md"
    post.write_text("![x](/img/uploads/2025/02/pic.png)")
    (uploads / "pic.png").write_bytes(b"png")

    om.main()

    assert post.read_text() == "![x](/img/uploads/2025/02/pic.webp)"
    assert not (uploads / "pic.png").exists(), "the original is removed once converted"


def test_failed_conversion_leaves_both_the_file_and_its_reference(site, monkeypatch):
    """Mutation proving this: drop `rel in failed` from repl() and the reference
    is rewritten to a .webp that was never produced — a guaranteed 404. Two
    images 404'd in production once already; this is that failure mode."""
    root, uploads = site
    post = root / "content" / "post.md"
    post.write_text("![x](/img/uploads/2025/02/broken.png)")
    (uploads / "broken.png").write_bytes(b"png")

    monkeypatch.setattr(om, "img_width", lambda p: 800)
    monkeypatch.setattr(om.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())

    om.main()

    assert post.read_text() == "![x](/img/uploads/2025/02/broken.png)", \
        "a reference must not be rewritten to a file that was never created"
    assert (uploads / "broken.png").exists(), "the original must survive a failed convert"


def test_oversized_images_are_downscaled_and_small_ones_are_not(site, monkeypatch):
    calls = []

    def fake_run(args, *a, **k):
        if args[0] == "cwebp":
            calls.append(args)
            Path(args[-1]).write_bytes(b"webp")
        return type("R", (), {"returncode": 0, "stdout": ""})()

    root, uploads = site
    (root / "content" / "post.md").write_text(
        "![a](/img/uploads/2025/02/big.png) ![b](/img/uploads/2025/02/small.png)")
    (uploads / "big.png").write_bytes(b"png")
    (uploads / "small.png").write_bytes(b"png")
    monkeypatch.setattr(om.subprocess, "run", fake_run)
    monkeypatch.setattr(om, "img_width", lambda p: 2400 if "big" in p.name else 900)

    om.main()

    by_name = {[a for a in c if a.endswith(".png")][0].split("/")[-1]: c for c in calls}
    assert "-resize" in by_name["big.png"], "a 2400px image must be downscaled"
    assert "-resize" not in by_name["small.png"], "a 900px image must never be upscaled"


# --- spec 008 SC-006: idempotence (previously OWED, never verified) ----------

def test_second_run_is_a_noop(site, stub_tools):
    """specs/008-media-optimization/spec.md SC-006. Documented as re-runnable
    after a re-migration; never verified until now."""
    root, uploads = site
    post = root / "content" / "post.md"
    post.write_text("![x](/img/uploads/2025/02/pic.png)")
    (uploads / "pic.png").write_bytes(b"png")

    om.main()
    after_first = (post.read_text(), sorted(p.name for p in uploads.rglob("*") if p.is_file()))

    om.main()
    after_second = (post.read_text(), sorted(p.name for p in uploads.rglob("*") if p.is_file()))

    assert after_second == after_first, "a second run must change nothing (SC-006)"
    assert after_first[1] == ["pic.webp"]


def test_empty_directories_are_removed(site, stub_tools):
    root, uploads = site
    (root / "content" / "post.md").write_text("no refs")
    (uploads / "2024").mkdir(parents=True, exist_ok=True)

    om.main()

    assert not (uploads / "2024").exists()
