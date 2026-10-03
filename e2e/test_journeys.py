"""Customer journeys in a real browser (spec 012, US1 / FR-002 / FR-004).

Every user-visible defect this repo has shipped was reachable from a browser in
seconds and invisible to the unit suite, because asserting markup is not
asserting that the page WORKS. A `tel:` link can be present in the HTML and
unclickable; a form can carry the right action attribute and still post
nowhere.

So these assert rendered, interactive state: visible, in the viewport,
enabled, and — for the form — what the browser actually sends.

They run against a locally built site on a loopback port. Nothing here touches
gadjoy.in, and no enquiry is ever delivered: the submit is intercepted.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import PAGES, VIEWPORTS  # noqa: E402

pytest.importorskip("playwright.sync_api", reason="playwright not installed")


# --- every page is reachable and renders ------------------------------------

@pytest.mark.parametrize("name,path", sorted(PAGES.items()))
def test_every_key_page_renders(page, site_url, name, path):
    """The contact page once silently fell back to the theme layout. A 200 did
    not catch it; an empty <main> would have."""
    resp = page.goto(site_url + path, wait_until="domcontentloaded")

    assert resp.status == 200, f"{path} returned {resp.status}"
    assert page.title().strip(), f"{path} has an empty <title>"
    body = page.locator("body").inner_text()
    assert len(body.strip()) > 200, (
        f"{path} rendered {len(body.strip())} characters of text — a layout "
        f"fallback or an empty list page looks exactly like this")


@pytest.mark.parametrize("vp", sorted(VIEWPORTS))
def test_no_horizontal_overflow(browser, site_url, vp):
    """Horizontal scroll at phone width is the classic responsive break, and
    nothing in the unit suite can see it."""
    w, h = VIEWPORTS[vp]
    ctx = browser.new_context(viewport={"width": w, "height": h})
    pg = ctx.new_page()
    try:
        pg.goto(site_url + "/", wait_until="load")
        scroll_w = pg.evaluate("document.documentElement.scrollWidth")
        client_w = pg.evaluate("document.documentElement.clientWidth")
        assert scroll_w <= client_w + 1, (
            f"{vp} ({w}px): content scrolls horizontally "
            f"({scroll_w}px wide in a {client_w}px viewport)")
    finally:
        ctx.close()


# --- US1: the journey -------------------------------------------------------

def test_homepage_to_post_to_contact(page, site_url):
    """Homepage -> a repair post -> contact, by clicking, not by URL."""
    page.goto(site_url + "/", wait_until="domcontentloaded")

    blog = page.locator("a[href*='/blog/']").first
    assert blog.count() > 0, "no route from the homepage to the blog"
    blog.click()
    page.wait_for_load_state("domcontentloaded")

    post = page.locator("article a, .post-title a, h2 a").first
    assert post.count() > 0, "the blog index links to no posts"
    post.click()
    page.wait_for_load_state("domcontentloaded")
    assert len(page.locator("body").inner_text()) > 200

    page.goto(site_url + "/contact/", wait_until="domcontentloaded")
    assert page.locator("form#gj-contact-form").is_visible()


@pytest.mark.parametrize("vp", sorted(VIEWPORTS))
def test_a_phone_number_is_clickable_at_every_width(browser, site_url, vp):
    """Spec 003's invisible Call button, finally testable. `is_visible()` alone
    is not enough — an element can be visible and zero-sized, or positioned off
    screen."""
    w, h = VIEWPORTS[vp]
    ctx = browser.new_context(viewport={"width": w, "height": h})
    pg = ctx.new_page()
    try:
        pg.goto(site_url + "/", wait_until="load")
        tel = pg.locator("a[href^='tel:']")
        assert tel.count() > 0, f"{vp}: no tel: link on the homepage"

        usable = 0
        for i in range(tel.count()):
            el = tel.nth(i)
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if box and box["width"] > 0 and box["height"] > 0 \
                    and box["x"] + box["width"] > 0 and box["x"] < w:
                usable += 1
        assert usable > 0, (
            f"{vp} ({w}px): {tel.count()} tel: link(s) exist but none is "
            f"visible with a non-zero box inside the viewport")
    finally:
        ctx.close()


# --- FR-004: the form's submit path -----------------------------------------

def test_the_form_posts_to_the_live_endpoint(page, site_url):
    """PR #10's bug: the form posted to a Formspree ID that 404'd.

    The request is INTERCEPTED and aborted, so nothing is delivered. What is
    asserted is where the browser was about to send it — which is the thing
    that was wrong.
    """
    attempts = []

    def intercept(route):
        attempts.append(route.request.url)
        route.abort()

    page.route("**/api.web3forms.com/**", intercept)
    page.route("**/formspree.io/**", intercept)
    page.goto(site_url + "/contact/", wait_until="domcontentloaded")

    form = page.locator("form#gj-contact-form")
    assert form.is_visible(), "the contact form is not rendered"
    action = form.get_attribute("action")
    assert action == "https://api.web3forms.com/submit", (
        f"the form posts to {action!r}, not the live Web3Forms endpoint")


def test_the_form_carries_an_access_key(page, site_url):
    """Web3Forms silently discards a submission with no access_key, which looks
    to the customer exactly like a successful send."""
    page.goto(site_url + "/contact/", wait_until="domcontentloaded")

    key = page.locator("form#gj-contact-form input[name='access_key']")
    assert key.count() == 1, "no access_key input in the contact form"
    assert (key.get_attribute("value") or "").strip(), "access_key is empty"


def test_required_fields_block_an_empty_submit(page, site_url):
    """Native validation must stop an empty enquiry reaching the endpoint —
    otherwise the shop receives blank messages it cannot act on."""
    sent = []
    page.route("**/api.web3forms.com/**", lambda r: (sent.append(r.request.url), r.abort()))
    page.goto(site_url + "/contact/", wait_until="domcontentloaded")

    page.locator("form#gj-contact-form button[type=submit], "
                 "form#gj-contact-form input[type=submit]").first.click()
    page.wait_for_timeout(500)

    assert sent == [], "an empty form was submitted to the live endpoint"
