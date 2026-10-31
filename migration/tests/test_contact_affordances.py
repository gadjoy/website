"""One contact affordance per region, per page (spec 016, FR-007 / SC-001).

THIS IS THE TEST PR #12 DID NOT HAVE. That PR fixed duplicated contact icons
with 7 lines of CSS capped at 767px — the one breakpoint nobody complained
about — and shipped with nothing to stop it recurring. It recurred.

WHY "PER REGION" AND NOT "PER PAGE"
A flat per-page cap is the wrong rule and would be gamed within a week. A
customer at the bottom of a long repair post should not have to scroll back up
to find a phone number, so the footer legitimately repeats what the topbar
offers. What is NOT legitimate is the same region offering the same route twice
— which is exactly what the topbar did, rendering the number as plain text in
one column and as an icon link in another.
"""
import re

import pytest

from conftest import REPO_ROOT

# A region is a part of the page a visitor encounters separately.
# The topbar is `<div id=top>` in this theme, NOT a "top-bar" class. The first
# version of these patterns guessed the class name, matched nothing, and the
# counting test passed while the duplication was live — caught immediately by
# test_the_region_patterns_actually_match_something, which exists for exactly
# this. Anchored on the real markup, confirmed against the built output.
REGION_PATTERNS = {
    "topbar": re.compile(r"<div id=[\"']?top[\"']?[ >].*?</header>", re.S | re.I),
    "footer": re.compile(r"<footer.*?</footer>", re.S | re.I),
}

# tel:, wa.me and mailto: are three different ROUTES. One of each per region is
# fine — offering a call and a WhatsApp is a choice, not a duplicate. Two tel:
# links in the same region is the defect.
ROUTES = {
    "call": re.compile(r"href=[\"']?tel:", re.I),
    "whatsapp": re.compile(r"(?:href=[\"']?[^\"'>]*)?wa\.me/", re.I),
    "email": re.compile(r"href=[\"']?mailto:", re.I),
}

PAGES = ["index.html", "contact/index.html", "services/we-repair/index.html",
         "gallery/index.html", "blog/index.html"]


def _pages(built_site):
    for rel in PAGES:
        p = built_site / rel
        if p.is_file():
            yield rel, p.read_text(encoding="utf-8", errors="ignore")


def _region_text(html, region):
    m = REGION_PATTERNS[region].search(html)
    return m.group(0) if m else ""


def test_no_region_offers_the_same_route_twice(built_site):
    """SC-001. Written against the unfixed tree; the topbar fails it."""
    offenders = []
    for rel, html in _pages(built_site):
        for region in REGION_PATTERNS:
            text = _region_text(html, region)
            if not text:
                continue
            for route, rx in ROUTES.items():
                n = len(rx.findall(text))
                if n > 1:
                    offenders.append(f"{rel} [{region}] {route}x{n}")

    assert not offenders, (
        "a region offers the same contact route more than once:\n  "
        + "\n  ".join(offenders) +
        "\nOne route per region. The footer may repeat what the topbar offers — "
        "a visitor at the bottom of a long page should not scroll back up — but "
        "a single region must not offer the same route twice."
    )


def test_the_contact_page_does_not_link_to_itself_from_the_footer(built_site):
    """SC-003. A button reading 'Go to contact page', on the contact page."""
    p = built_site / "contact" / "index.html"
    if not p.is_file():
        pytest.skip("contact page not built")
    footer = _region_text(p.read_text(encoding="utf-8", errors="ignore"), "footer")

    assert not re.search(r"href=[\"']?/contact/?[\"' >]", footer, re.I), (
        "the contact page's footer links to the contact page")


def test_no_tel_or_mailto_opens_a_new_tab(built_site):
    """SC-006. target=_blank on a tel: spawns a blank tab beside the dialer."""
    offenders = []
    for rel, html in _pages(built_site):
        for m in re.finditer(r"<a[^>]*href=[\"']?(?:tel:|mailto:)[^>]*>", html, re.I):
            if "_blank" in m.group(0):
                offenders.append(f"{rel}: {m.group(0)[:90]}")

    assert not offenders, f"tel:/mailto: links opening a new tab: {offenders}"


def test_internal_contact_links_carry_the_trailing_slash(built_site):
    """SC-005. `/contact` without the slash takes a redirect on every page."""
    offenders = []
    for rel, html in _pages(built_site):
        for m in re.finditer(r"href=[\"']?(/contact)(?![/\w-])", html, re.I):
            offenders.append(f"{rel}: {m.group(1)}")

    assert not offenders, (
        f"internal links to /contact without a trailing slash (each costs a "
        f"redirect): {sorted(set(offenders))}")


def test_the_region_patterns_actually_match_something(built_site):
    """Guards the guard. If the theme's markup changes, every test above would
    silently pass by finding no regions at all — the failure mode that let the
    brand-count check pass while the claim was live."""
    home = (built_site / "index.html").read_text(encoding="utf-8", errors="ignore")
    for region in REGION_PATTERNS:
        assert _region_text(home, region), (
            f"the {region!r} pattern matched nothing on the homepage; every "
            f"affordance test is now blind")
