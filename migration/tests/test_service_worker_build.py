"""The service worker as BUILT: its cache version is stamped by the build, and its
registration is an external script a Content-Security-Policy cannot silently block.

Fleet PWA standard (FLEET.md, 2026-11-07). Both defects were found elsewhere first:

- A hand-bumped version ("Bump on any change to this file's behaviour") is never bumped,
  so activation deletes nothing and every visitor keeps every old asset — folio until #70.
  This site shipped `gadjoy-v1`, with a cache-first asset cache that includes images.
- An inline `navigator.serviceWorker.register(...)` is blocked by `script-src 'self'`, and
  because registration swallows its own errors the PWA stops with no error anywhere —
  artbypriti #26 had to move it out of line. This site has no CSP yet; the day it gets one,
  an inline registration would fail exactly that way.
"""
import re

import pytest

pytestmark = pytest.mark.build

# What layouts/partials/custom_headers.html stamps: the commit in CI (HUGO_BUILD_COMMIT),
# the UTC build time otherwise.
STAMPED = re.compile(r"""\bconst VERSION\s*=\s*['"]gadjoy-(?:[0-9a-f]{7,40}|[0-9]{14})['"]""")
# One page per layout that includes custom_headers.html. offline/index.html is deliberately
# script-free (layouts/_default/offline.html) and is not expected to register anything.
KEY_PAGES = ["index.html", "contact/index.html", "gallery/index.html", "blog/index.html"]
EXTERNAL_TAG = re.compile(r"""<script[^>]*\bsrc=["']?(/js/sw-register[^"' >]*\.js)["']?[^>]*>""")


def test_the_built_worker_carries_a_build_stamped_version(built_site):
    worker = (built_site / "sw.js").read_text(encoding="utf-8")
    assert STAMPED.search(worker), (
        "sw.js does not carry a build-stamped VERSION (e.g. gadjoy-<commit>); a hand-bumped "
        "or unrendered one leaves every old cache on returning visitors' phones. Found: "
        + (re.search(r"const VERSION[^;]*;", worker) or [""])[0])
    assert "{{" not in worker, "sw.js still contains an unrendered template placeholder"


@pytest.mark.parametrize("page", KEY_PAGES)
def test_no_page_registers_the_worker_inline(built_site, page):
    html = (built_site / page).read_text(encoding="utf-8")
    inline = [s for s in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)
              if "serviceWorker.register" in s]
    assert not inline, (
        f"{page} registers the service worker in an inline script; a strict "
        "script-src 'self' would block it silently")


@pytest.mark.parametrize("page", KEY_PAGES)
def test_every_page_loads_the_external_registration_script(built_site, page):
    html = (built_site / page).read_text(encoding="utf-8")
    m = EXTERNAL_TAG.search(html)
    assert m, f"{page} does not load the external sw-register script"
    script = built_site / m.group(1).lstrip("/")
    assert script.is_file(), f"{page} loads {m.group(1)}, which is not in the build"
    body = script.read_text(encoding="utf-8")
    assert "serviceWorker.register" in body, f"{m.group(1)} never registers the worker"
    assert "data-sw-url" in m.group(0) or "swUrl" in body, "the worker URL never reaches the script"
