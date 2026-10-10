"""The PWA, asserted in a real browser (spec 013, SC-003..SC-010).

A manifest that parses and a service worker that registers are necessary and
nowhere near sufficient. What matters is whether the thing works with the
network off, and that can only be asserted by turning the network off.

THE TRAP THESE TESTS ARE WRITTEN AROUND: "go offline, assert the page rendered"
passes when the BROWSER serves its own error page, because that is a rendered
page. Every offline assertion below names Gadjoy content specifically — the
shop's phone number, the offline page's own heading — so a browser error cannot
satisfy it.

The service worker does not register on localhost (see custom_headers.html), so
these tests register it explicitly from the page. That keeps `hugo server` free
of a stale worker while still testing the real sw.js.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import REPO_ROOT  # noqa: E402

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

PHONE_DIGITS = "9110624049"


def register_sw(pg, site_url):
    """Register and wait for activation, returning the controller scope."""
    pg.goto(site_url + "/", wait_until="load")
    return pg.evaluate("""async () => {
        const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
        await navigator.serviceWorker.ready;
        // Wait for a controller, which only exists once the worker is active
        // AND has claimed this client.
        if (!navigator.serviceWorker.controller) {
            await new Promise(r => {
                navigator.serviceWorker.addEventListener('controllerchange', r,
                                                          { once: true });
                setTimeout(r, 3000);
            });
        }
        return reg.scope;
    }""")


# --- manifest ----------------------------------------------------------------

def test_the_manifest_is_served_and_linked(page, site_url):
    page.goto(site_url + "/", wait_until="domcontentloaded")
    href = page.locator("link[rel=manifest]").first.get_attribute("href")
    assert href, "no <link rel=manifest> in the document head"

    resp = page.request.get(site_url + href)
    assert resp.status == 200, f"{href} returned {resp.status}"
    data = resp.json()
    assert data["name"] and data["start_url"] == "/" and data["display"] == "standalone"


def test_the_manifest_values_come_from_hugo_yaml(page, site_url):
    """Principle X. Mutation proving this: change the title in hugo.yaml and the
    manifest must follow; hard-code it in the template and this fails."""
    import yaml
    cfg = yaml.safe_load((REPO_ROOT / "hugo.yaml").read_text())

    page.goto(site_url + "/", wait_until="domcontentloaded")
    data = page.request.get(site_url + "/manifest.webmanifest").json()

    assert data["name"] == cfg["title"]
    assert data["short_name"] == cfg["params"]["pwa"]["short_name"]
    assert data["theme_color"] == cfg["params"]["pwa"]["theme_color"]


def test_every_declared_icon_is_actually_served(page, site_url):
    """A manifest that names a missing icon fails installability silently."""
    page.goto(site_url + "/", wait_until="domcontentloaded")
    data = page.request.get(site_url + "/manifest.webmanifest").json()

    assert data["icons"], "manifest declares no icons"
    for icon in data["icons"]:
        r = page.request.get(site_url + icon["src"])
        assert r.status == 200, f"{icon['src']} -> {r.status}"


def test_the_manifest_declares_a_maskable_icon(page, site_url):
    page.goto(site_url + "/", wait_until="domcontentloaded")
    data = page.request.get(site_url + "/manifest.webmanifest").json()

    purposes = {i.get("purpose") for i in data["icons"]}
    assert "maskable" in purposes
    assert "any" in purposes, "a maskable-only icon set looks wrong outside launchers"


# --- installability ----------------------------------------------------------

def test_the_installability_criteria_are_met(page, site_url):
    """Chrome's requirements: served over a secure context (localhost counts),
    a manifest with name, start_url, display and a >=192px and >=512px icon,
    plus a fetch handler in the service worker."""
    page.goto(site_url + "/", wait_until="domcontentloaded")
    data = page.request.get(site_url + "/manifest.webmanifest").json()

    sizes = {i["sizes"] for i in data["icons"]}
    assert "192x192" in sizes and "512x512" in sizes
    assert data.get("name") and data.get("short_name")
    assert data.get("display") in {"standalone", "fullscreen", "minimal-ui"}

    sw = page.request.get(site_url + "/sw.js")
    assert sw.status == 200
    assert "addEventListener('fetch'" in sw.text(), (
        "the worker has no fetch handler, so the browser will not treat the "
        "site as installable")


# --- service worker ----------------------------------------------------------

def test_the_worker_registers_and_controls_the_root(page, site_url):
    scope = register_sw(page, site_url)

    assert scope.endswith("/"), f"scope {scope!r} is not the site root"
    assert page.evaluate("!!navigator.serviceWorker.controller"), (
        "the worker registered but never claimed the page")


def test_the_worker_does_not_register_itself_on_localhost(page, site_url):
    """The site's own registration script skips localhost so `hugo server` is
    not shadowed by a stale worker. Asserted so that guard cannot quietly go."""
    page.goto(site_url + "/", wait_until="load")
    page.wait_for_timeout(500)
    regs = page.evaluate("navigator.serviceWorker.getRegistrations().then(r => r.length)")

    assert regs == 0, (
        "the page registered a service worker on localhost; hugo server would "
        "then be served from a stale cache")


# --- offline (the point of the whole thing) ---------------------------------

def test_a_visited_page_still_renders_offline(page, site_url):
    """US2/SC-005."""
    register_sw(page, site_url)
    page.goto(site_url + "/contact/", wait_until="load")
    assert page.locator("form#gj-contact-form").is_visible()

    page.context.set_offline(True)
    try:
        page.reload(wait_until="domcontentloaded")
        assert page.locator("form#gj-contact-form").count() == 1, (
            "a previously visited page did not come back from cache offline")
    finally:
        page.context.set_offline(False)


def test_an_unvisited_page_shows_the_gadjoy_offline_page(page, site_url):
    """US3/SC-006, and the trap this file is written around.

    Asserting "something rendered" would pass on Chromium's own error page.
    This asserts Gadjoy's offline page specifically.
    """
    register_sw(page, site_url)
    page.context.set_offline(True)
    try:
        page.goto(site_url + "/services/we-build/?never-visited=1",
                  wait_until="domcontentloaded")
        body = page.locator("body").inner_text()

        assert "offline" in body.lower(), "not the Gadjoy offline page"
        assert PHONE_DIGITS in body.replace(" ", ""), (
            "the offline page does not carry the shop's phone number — which is "
            "the entire reason it exists (SC-007)")
    finally:
        page.context.set_offline(False)


def test_the_offline_page_carries_the_full_contact_payload(page, site_url):
    """SC-007: address, phone, WhatsApp and hours."""
    page.goto(site_url + "/offline/", wait_until="domcontentloaded")
    body = page.locator("body").inner_text()
    html = page.content()

    assert PHONE_DIGITS in body.replace(" ", ""), "no phone number"
    assert "Varthur" in body, "no street address"
    assert "wa.me" in html, "no WhatsApp link"
    assert "Mon" in body, "no opening hours"


def test_the_offline_page_does_not_claim_the_whole_site_works(page, site_url):
    """FR-011. Overclaiming here is the kind of thing that reads as dishonest
    the moment a customer taps a link and gets nothing."""
    page.goto(site_url + "/offline/", wait_until="domcontentloaded")
    body = page.locator("body").inner_text().lower()

    assert "already opened" in body or "needs a connection" in body, (
        "the offline page should say what does and does not work offline")


# --- the POST guard (FR-008) -------------------------------------------------

def test_a_same_origin_post_is_not_intercepted(page, site_url):
    """FR-008, isolating the METHOD guard.

    This must be same-origin. An earlier version posted to api.web3forms.com,
    which is cross-origin — so the worker's origin check returned early and the
    test passed with the method guard deleted. It was vacuous, and only the
    mutation run revealed it. Posting same-origin is what makes
    `request.method !== 'GET'` the only thing that can let it through.

    Why it matters: a queued or replayed enquiry is worse than a failed one.
    The customer believes it was sent and waits for a reply that never comes.
    """
    register_sw(page, site_url)
    seen = []
    page.route("**/__probe__", lambda r: (
        seen.append(r.request.method),
        r.fulfill(status=200, content_type="text/html", body="<p>probe ok</p>")))

    page.goto(site_url + "/contact/", wait_until="load")
    # A FORM submission, so the request is a NAVIGATION. That is what makes the
    # method guard observable: a navigation POST is the one non-GET that would
    # otherwise fall into htmlNetworkFirst, where cache.put() on a POST throws.
    # A plain fetch() POST to an extensionless path matches no branch and falls
    # through to the network even with the guard deleted — which is why the
    # first two versions of this test were vacuous.
    page.evaluate("""(base) => {
        const f = document.createElement('form');
        f.method = 'POST';
        f.action = base + '/__probe__';
        document.body.appendChild(f);
        f.submit();
    }""", site_url)
    page.wait_for_timeout(1200)

    assert seen == ["POST"], (
        f"a same-origin navigation POST did not reach the network untouched, "
        f"saw {seen}. The worker must return early for any non-GET request.")
    assert "probe ok" in page.content(), (
        "the POST response did not render — the worker interfered with it")


def test_a_cross_origin_request_is_not_intercepted(page, site_url):
    """FR-008, isolating the ORIGIN guard. The form's real endpoint is
    cross-origin, so this is the path a live enquiry actually takes."""
    register_sw(page, site_url)
    seen = []
    page.route("**/api.web3forms.com/**",
               lambda r: (seen.append(r.request.method), r.abort()))

    page.goto(site_url + "/contact/", wait_until="load")
    page.evaluate("""async () => {
        await fetch('https://api.web3forms.com/submit', {
            method: 'POST', body: new FormData(),
        }).catch(() => {});
    }""")
    page.wait_for_timeout(500)

    assert seen == ["POST"], f"the cross-origin POST was intercepted, saw {seen}"


# --- versioning and freshness ------------------------------------------------

def test_html_is_fetched_network_first_not_served_stale(page, site_url, built_site):
    """SC-010. The shop publishes repair posts and corrects claims on the site;
    a cache-first HTML strategy would serve yesterday's page indefinitely.

    Proven by changing the file on disk between two online loads. Mutation
    proving the test can fail: swap htmlNetworkFirst for a cache-first lookup
    and the sentinel never appears.
    """
    register_sw(page, site_url)
    target = built_site / "services" / "we-build" / "index.html"
    original = target.read_text()

    page.goto(site_url + "/services/we-build/", wait_until="load")
    assert "GADJOY-SENTINEL" not in page.content()

    try:
        target.write_text(original.replace("</body>", "<p>GADJOY-SENTINEL</p></body>"))
        page.reload(wait_until="load")
        assert "GADJOY-SENTINEL" in page.content(), (
            "the page was served from cache while online — HTML must be "
            "network-first so a published change is never served stale")
    finally:
        target.write_text(original)


def test_activating_a_new_version_deletes_the_old_caches(page, site_url):
    """SC-009/FR-009. A worker whose old caches survive serves a previous build
    forever, and clearing it needs devtools a customer does not have."""
    register_sw(page, site_url)

    stale = page.evaluate("""async () => {
        const c = await caches.open('gadjoy-v0-pages');
        await c.put('/stale-probe', new Response('old'));
        return (await caches.keys()).includes('gadjoy-v0-pages');
    }""")
    assert stale, "could not create a stale cache to test against"

    # Force a fresh activation: unregister, then register again.
    page.evaluate("""async () => {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(r => r.unregister()));
    }""")
    register_sw(page, site_url)
    page.wait_for_timeout(500)

    remaining = page.evaluate("caches.keys()")
    assert "gadjoy-v0-pages" not in remaining, (
        f"a previous version's cache survived activation: {remaining}")
    assert any(k.startswith("gadjoy-v1") for k in remaining), (
        f"the current version's caches are missing entirely: {remaining}")
