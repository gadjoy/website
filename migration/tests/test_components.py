"""Hero & card components (spec 019).

The guard that matters most here is test_every_project_class_has_a_rule. Two
pages — /services/ and /testimonials/ — shipped with cards styled by classes
that did not exist in any stylesheet, and every gate stayed green, because
nothing asked whether a class in the markup had a rule behind it.
"""
import re

from conftest import REPO_ROOT

CSS = REPO_ROOT / "static" / "css" / "custom.css"
LAYOUTS = REPO_ROOT / "layouts"
HERO_MARKUP = 'class="gadjoy-hero svc-hero"'


def _classes_used():
    used = {}
    for f in LAYOUTS.rglob("*.html"):
        for m in re.finditer(r'class="([^"{]+)"', f.read_text(encoding="utf-8")):
            for c in m.group(1).split():
                if c.startswith(("gj-", "gadjoy-")):
                    used.setdefault(c, str(f.relative_to(REPO_ROOT)))
    return used


def test_every_project_class_has_a_rule():
    """SC-005. Mutation proving this: delete every rule naming .gj-archive-note
    and it fails, naming the class and the template that uses it.

    Known limit, stated rather than hidden: a class mentioned only as an
    ANCESTOR (`.gj-review-card .g-stars`) counts as present, so an element whose
    own rule is gone but whose children are styled will pass. The defect this
    exists for — a class with no rule anywhere — is caught.
    """
    css = CSS.read_text(encoding="utf-8")
    missing = {c: where for c, where in _classes_used().items()
               if not re.search(r"\." + re.escape(c) + r"(?![\w-])", css)}

    assert not missing, (
        "classes used in templates with NO rule in custom.css — these elements "
        f"render unstyled: {missing}")


def test_hero_markup_lives_in_one_template():
    """SC-001. It was hand-copied into three layouts."""
    holders = [str(f.relative_to(REPO_ROOT)) for f in LAYOUTS.rglob("*.html")
               if HERO_MARKUP in f.read_text(encoding="utf-8")]

    assert holders == ["layouts/partials/page-hero.html"], (
        f"page-hero markup found in: {holders}")


def test_the_three_hero_pages_use_the_partial():
    for rel in ("_default/contact.html", "_default/services-list.html", "services/single.html"):
        assert 'partial "page-hero.html"' in (LAYOUTS / rel).read_text(encoding="utf-8"), rel


def test_the_card_surface_is_declared_once():
    """SC-003. White background + hairline border + medium shadow was repeated
    in every card rule."""
    css = CSS.read_text(encoding="utf-8")
    rules = re.findall(r"([^{}]+)\{([^}]*)\}", css)
    surfaces = [sel.strip() for sel, body in rules
                if "var(--line)" in body and "--gj-shadow-md" in body
                and re.search(r"background:\s*#fff", body)]

    assert len(surfaces) == 1, (
        f"the card surface is declared in {len(surfaces)} rules: {surfaces}")


def test_section_headings_draw_one_underline():
    """SC-006. The theme's full-width 5px border AND custom.css's short bar both
    rendered under every centred section heading."""
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.heading\.text-center h2\s*\{([^}]*)\}", css)

    assert m and re.search(r"border-bottom:\s*0", m.group(1)), (
        "centred section headings still inherit the theme's full-width border "
        "beneath the short bar — two underlines")


def test_no_link_is_neutralised_by_the_template_escaper(built_site):
    """Hugo replaces a URL it considers unsafe with the sentinel "#ZgotmplZ".

    This is a rule because it happened: moving the hero into a partial passed the
    tel: URL as a variable, the escaper rejected it, and the contact page's
    "Call us" button became href=#ZgotmplZ — a dead button on a repair shop's
    contact page. The visual baselines could never catch it: a link target is
    invisible in a screenshot. A local HTML comparison did.

    Mutation proving this: remove `| safeURL` from page-hero.html and this fails.
    """
    hits = [str(p.relative_to(built_site)) for p in built_site.rglob("*.html")
            if "ZgotmplZ" in p.read_text(encoding="utf-8", errors="ignore")]

    assert not hits, f"links neutralised to #ZgotmplZ on: {hits[:10]}"
