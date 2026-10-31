"""Design tokens, two dead pages, and the social cards (spec 017).

Written before the fixes. Both page defects were verified on the LIVE site
first, not taken from a planning note:

  /services/   returns 200 with class="blog-entries" and no entries, because
               the service pages are not blog posts. A customer following the
               nav lands on a blank page.
  _index.md    opens "## Bangalore's bench for when tech breaks." and no
               homepage layout renders .Content, so it has never been seen.
"""
import re

import pytest

from conftest import REPO_ROOT

CSS = REPO_ROOT / "static" / "css" / "custom.css"


def _read(site, rel):
    p = site / rel
    return p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""


# --- the dead pages ----------------------------------------------------------

def test_services_lists_the_services(built_site):
    """SC-003."""
    html = _read(built_site, "services/index.html")
    assert html, "/services/ was not built"

    for svc in ("/services/we-repair/", "/services/we-build/"):
        assert svc in html, f"/services/ does not link to {svc}"


def test_services_is_not_an_empty_blog_listing(built_site):
    """SC-004. It renders the blog list layout today, with nothing in it."""
    html = _read(built_site, "services/index.html")
    # Scoped to the page BODY: the footer carries a legitimate "Recent posts"
    # widget that also uses .blog-entries, so checking the whole document would
    # fail forever on something that is not the defect.
    body = html.split("<footer")[0]

    assert "blog-entries" not in body, (
        "/services/ is still rendering the blog listing layout in its body; "
        "the service pages are not blog posts, so it comes out empty")


def test_the_homepage_renders_the_index_body(built_site):
    """SC-005. The copy exists and has never been displayed."""
    src = (REPO_ROOT / "content" / "_index.md").read_text(encoding="utf-8")
    body = src.split("---", 2)[-1].strip()
    if not body:
        pytest.skip("_index.md has no body")

    # First real sentence from the body, stripped of markdown heading marks.
    first = next(l.lstrip("# ").strip() for l in body.splitlines() if l.strip())
    html = _read(built_site, "index.html")

    # Hugo smart-quotes the markdown: ' becomes &rsquo;. Comparing the raw
    # source against rendered HTML therefore never matches, which cost a
    # debugging round here. Normalise both sides.
    def norm(t):
        return (t.replace("&rsquo;", "'").replace("\u2019", "'")
                 .replace("&amp;", "&"))

    first, html = norm(first), norm(html)

    assert first[:40] in html, (
        f"_index.md's body is not on the homepage. It opens {first[:60]!r} and "
        f"has never been rendered.")


# --- tokens ------------------------------------------------------------------

def test_shadows_and_radii_come_from_tokens():
    """SC-001. 16 shadows and 7 radii were not 16 and 7 intentions — they were
    a handful typed slightly differently."""
    css = CSS.read_text(encoding="utf-8")
    token_block = re.search(r":root\s*\{(.*?)\}", css, re.S)
    assert token_block, "no :root token block in custom.css"
    tokens = token_block.group(1)

    assert "--gj-shadow" in tokens, "no shadow tokens defined"
    assert "--gj-radius" in tokens, "no radius tokens defined"

    body = css[token_block.end():]
    literal_shadows = [
        m.group(0) for m in re.finditer(r"box-shadow:\s*([^;]+);", body)
        if "var(--gj-" not in m.group(1) and m.group(1).strip() not in ("none", "inherit")
    ]
    literal_radii = [
        m.group(0) for m in re.finditer(r"border-radius:\s*([^;]+);", body)
        if "var(--gj-" not in m.group(1) and m.group(1).strip() not in ("0", "50%", "999px", "inherit")
    ]

    assert not literal_shadows, (
        f"{len(literal_shadows)} box-shadow literals outside the token block: "
        f"{literal_shadows[:4]}")
    assert not literal_radii, (
        f"{len(literal_radii)} border-radius literals outside the token block: "
        f"{literal_radii[:4]}")


def test_the_whatsapp_number_is_declared_once():
    """SC-002. Hard-coded in four files; a number change was four edits and a
    hope."""
    hits = []
    for d in ("layouts", "static"):
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.suffix in {".html", ".css", ".js"}:
                if "919110624049" in f.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(f.relative_to(REPO_ROOT)))

    assert not hits, (
        f"the WhatsApp number is hard-coded in: {hits}. Declare it once in "
        f"hugo.yaml and read it everywhere.")


# --- sharing -----------------------------------------------------------------

@pytest.mark.parametrize("rel", ["index.html", "contact/index.html",
                                 "services/we-repair/index.html"])
def test_every_page_carries_open_graph_tags(built_site, rel):
    """SC-006. The shop's primary channel is WhatsApp, where a shared link
    currently renders as a bare URL."""
    html = _read(built_site, rel)
    # --minify strips attribute quotes, so do not require them.
    for prop in ("og:title", "og:description", "og:image", "og:url"):
        assert re.search(rf'property=["\']?{re.escape(prop)}["\']?', html), (
            f"{rel} has no {prop}")


def test_the_og_image_resolves_to_a_real_file(built_site):
    """SC-007. A card pointing at a 404 is worse than no card: the link renders
    broken rather than plain."""
    html = _read(built_site, "index.html")
    m = re.search(r'property=["\']?og:image["\']?[^>]*content=["\']?([^"\'\s>]+)', html)
    assert m, "no og:image"
    path = m.group(1).split("//", 1)[-1].split("/", 1)[-1]

    assert (built_site / path).is_file(), f"og:image points at a missing file: {m.group(1)}"


@pytest.mark.parametrize("rel", ["contact/index.html", "blog/index.html"])
def test_page_titles_carry_the_business_name(built_site, rel):
    """SC-008. A browser tab reading only "Contact" identifies nothing."""
    html = _read(built_site, rel)
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    assert m, f"{rel} has no <title>"

    assert "Gadjoy" in m.group(1), (
        f"{rel} title is {m.group(1)!r} — it does not name the business")
