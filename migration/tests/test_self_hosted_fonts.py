"""Sora and Inter are served from gadjoy.in, and the files agree with fonts.css.

Spec 020. The fonts came from Google, so the stylesheet waited on a third party,
every page view was reported to it, and whether the faces had arrived before a
screenshot was a race the visual gate had to learn to wait out.

The failure these guard against is a SILENT one: a font URL that 404s does not
error anywhere, the browser just falls back to a system face. Spec 017 shipped
exactly that once (an @import pushed below a rule) and only the baselines saw it.
"""
import re

from conftest import REPO_ROOT

FONTS_CSS = REPO_ROOT / "static" / "css" / "fonts.css"
FONT_DIR = REPO_ROOT / "static" / "fonts"
GOOGLE_FONTS_CSS2 = re.compile(r"fonts\.googleapis\.com/css2|fonts\.gstatic\.com")

# The weights custom.css asks for. A weight missing here is SYNTHESISED by the
# browser (faux bold), which looks wrong and no test of "the font loaded" sees.
WEIGHTS = {"Sora": {"600", "700", "800"}, "Inter": {"400", "500", "600", "700"}}


def _shipped_sources():
    yield from (REPO_ROOT / "layouts").rglob("*.html")
    yield from (REPO_ROOT / "static" / "css").glob("*.css")


def _faces():
    css = FONTS_CSS.read_text(encoding="utf-8")
    return re.findall(r"@font-face\s*\{(.*?)\}", css, re.S)


def test_no_shipped_file_references_google_fonts():
    """SC-001 / FR-002."""
    offenders = [str(p.relative_to(REPO_ROOT)) for p in _shipped_sources()
                 if GOOGLE_FONTS_CSS2.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert not offenders, f"still loading Sora/Inter from Google: {offenders}"


def test_every_font_url_resolves_and_every_file_is_used():
    """SC-002 / FR-003 — both directions: a missing file is a silent fallback,
    an orphan is dead weight nobody will ever notice."""
    urls = re.findall(r"url\(([^)]+)\)", FONTS_CSS.read_text(encoding="utf-8"))
    assert urls, "fonts.css declares no font files"
    referenced = set()
    for u in urls:
        u = u.strip("'\"")
        assert u.startswith("/fonts/"), f"{u} is not self-hosted"
        referenced.add(u[len("/fonts/"):])
    on_disk = {p.name for p in FONT_DIR.glob("*") if p.is_file()}
    assert referenced - on_disk == set(), f"fonts.css names missing files: {sorted(referenced - on_disk)}"
    assert on_disk - referenced == set(), f"unreferenced font files: {sorted(on_disk - referenced)}"
    for name in on_disk:
        assert (FONT_DIR / name).read_bytes()[:4] == b"wOF2", f"{name} is not a woff2 file"


def test_fonts_css_declares_the_weights_the_site_uses():
    """SC-003 — and each at the basic-latin range, which is what English text needs."""
    found = {fam: set() for fam in WEIGHTS}
    for face in _faces():
        fam = re.search(r"font-family:\s*'([^']+)'", face).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", face).group(1)
        if fam in found and "U+0000-00FF" in face:
            found[fam].add(weight)
    for fam, weights in WEIGHTS.items():
        assert weights <= found[fam], f"{fam} latin missing weights {sorted(weights - found[fam])}"


def test_built_pages_load_the_self_hosted_fonts(built_site):
    """SC-004 — every full page links fonts.css, and before custom.css so the
    faces are declared by the time the rules that use them apply."""
    link = re.compile(r"""href=["']?/css/fonts\.css""")
    custom = re.compile(r"""href=["']?/css/custom\.css""")
    checked = 0
    for page in built_site.rglob("*.html"):
        html = page.read_text(encoding="utf-8", errors="ignore")
        c = custom.search(html)
        if not c:
            continue  # redirect stubs and fragments carry no stylesheet
        checked += 1
        f = link.search(html)
        assert f, f"{page.relative_to(built_site)} does not load fonts.css"
        assert f.start() < c.start(), f"{page.relative_to(built_site)} loads fonts.css after custom.css"
    assert checked > 100, f"only {checked} pages checked — the selector is matching nothing"
