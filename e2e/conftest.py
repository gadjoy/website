"""Fixtures for the end-to-end suite (spec 012, phase C).

The site is built with the pinned Hugo and served from a loopback port, so the
tests exercise the real built output rather than a dev server with different
behaviour. Nothing here talks to gadjoy.in: these run on a PR, before anything
is published.
"""
import functools
import http.server
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = Path(__file__).resolve().parent / "baselines"

# Captured at both widths. 1440 is the common desktop content width; 390 is an
# iPhone 14/15 logical width and the one the invisible-Call-button defect lived
# at (spec 003, previously marked untestable).
VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}

# The pages a customer actually reaches. Kept short on purpose: a baseline per
# page is a maintenance cost, and 3,630 pages are built.
PAGES = {
    "home": "/",
    "contact": "/contact/",
    "gallery": "/gallery/",
    "we-repair": "/services/we-repair/",
    "we-build": "/services/we-build/",
    "blog": "/blog/",
    "post": "/2021/12/17/redmi-4-dead-condition/",
}

# Pages whose length is editorial and grows. A full-page baseline of these
# churns every time a post is published — a baseline that must be regenerated
# on unrelated changes stops being evidence and starts being a chore, and the
# chore is what gets skipped. Measured first: a full-page gallery capture is
# 9.7 MB and the whole set was 19 MB, in a repo already carrying a 2.99 GiB
# pack. These are captured at viewport height instead.
#
# The trade-off, stated rather than hidden: a layout break BELOW the fold on
# these two pages is not covered. Assert such a thing in a journey test, which
# does not care how long the page is.
VIEWPORT_ONLY = {"gallery", "blog"}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def serve_port():
    """Chosen BEFORE the build, because Hugo bakes baseURL into absolute links.

    Building with a baseURL whose port does not match the server sends every
    internal link to port 80, where Chromium lands on chrome-error://. The
    journey test caught that immediately — which is the point of clicking links
    rather than calling goto() with URLs the test made up itself.
    """
    return free_port()


@pytest.fixture(scope="session")
def built_site(tmp_path_factory, serve_port):
    """`hugo` into a temp dir. Session-scoped: the build takes ~9s."""
    out = tmp_path_factory.mktemp("site")
    proc = subprocess.run(
        ["hugo", "--destination", str(out),
         "--baseURL", f"http://127.0.0.1:{serve_port}/"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, f"hugo build failed:\n{proc.stderr[-2000:]}"
    assert (out / "index.html").is_file(), "hugo produced no index.html"
    return out


@pytest.fixture(scope="session")
def site_url(built_site, serve_port):
    port = serve_port
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(built_site))

    class Quiet(http.server.ThreadingHTTPServer):
        daemon_threads = True

    srv = Quiet(("127.0.0.1", port), handler)
    # Silence the per-request log; a 3,000-asset page makes it unreadable.
    handler.func.log_message = lambda *a, **k: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


@pytest.fixture(scope="session")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    try:
        yield pg
    finally:
        ctx.close()
