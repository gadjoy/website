"""A self-test for scripts/smoke.sh (spec 012, FR-008 / SC-008).

smoke.sh is the last gate between a deploy and a customer, and it is the only
one that sees what the world actually receives. It has no test of its own, so
nothing stops it from silently ceasing to check: delete an assertion, or let a
`grep` always succeed, and it still prints SMOKE PASSED.

That is not a hypothetical shape — `| grep -q` under `pipefail` was exactly this
defect in house-gates 1.5.0.

So the important direction here is the FAILING one. Asserting that a healthy
site passes proves only that the script runs; asserting that a broken site fails
proves it is still looking. Every check in smoke.sh gets the broken-site
treatment via `broken`, below.

The fixture server is plain http.server on a loopback port. SMOKE_RETRIES=1 and
SMOKE_SLEEP=0 keep the retry loop from making this slow.
"""
import shutil
import socket
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import REPO_ROOT

SMOKE = REPO_ROOT / "scripts" / "smoke.sh"

PAGES = {
    "index.html": '<html><body>Over 15,000 devices repaired</body></html>',
    "contact/index.html":
        '<html><body><form class="gj-contact-form" '
        'action="https://api.web3forms.com/submit"></form></body></html>',
    "gallery/index.html": "<html>gallery</html>",
    "services/we-repair/index.html": "<html>we repair</html>",
    "services/we-build/index.html": "<html>we build</html>",
    "blog/index.html": "<html>blog</html>",
    "2021/12/17/redmi-4-dead-condition/index.html": "<html>post</html>",
    "img/uploads/2021/12/Redmi-4-Before-Dead-Condition.webp": "fake-webp",
    "img/uploads/2021/12/Redmi-4-After-Dead-Condition.webp": "fake-webp",
}


class Quiet(SimpleHTTPRequestHandler):
    """Quiet, and 404s a directory with no index.html.

    http.server's default is to render a directory LISTING, which answers 200.
    GitHub Pages returns 404. Without this override the fixture is more
    forgiving than production and five "missing page" cases passed when they
    should have failed — the fixture, not smoke.sh, was wrong. A test harness
    that is laxer than the thing it simulates proves nothing (CON-VER-004).
    """

    def log_message(self, *a):
        pass

    def list_directory(self, path):
        self.send_error(404, "No index.html")
        return None


@pytest.fixture
def site(tmp_path):
    """Serve a healthy copy of the site; `drop` removes or rewrites a page."""
    root = tmp_path / "site"
    for rel, body in PAGES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    httpd = ThreadingHTTPServer(
        ("127.0.0.1", port), partial(Quiet, directory=str(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    class Site:
        url = f"http://127.0.0.1:{port}"

        @staticmethod
        def drop(rel):
            (root / rel).unlink()

        @staticmethod
        def rewrite(rel, body):
            (root / rel).write_text(body)

    try:
        yield Site
    finally:
        httpd.shutdown()


def run_smoke(url):
    return subprocess.run(
        ["bash", str(SMOKE), url], capture_output=True, text=True, timeout=180,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "SMOKE_RETRIES": "1",
             "SMOKE_SLEEP": "0", "HOME": "/tmp"})


pytestmark = pytest.mark.skipif(
    shutil.which("curl") is None, reason="smoke.sh needs curl")


def test_a_healthy_site_passes(site):
    out = run_smoke(site.url)

    assert out.returncode == 0, out.stdout + out.stderr
    assert "SMOKE PASSED" in out.stdout


@pytest.mark.parametrize("rel,label", [
    ("index.html", "homepage"),
    ("contact/index.html", "contact page"),
    ("gallery/index.html", "gallery"),
    ("services/we-repair/index.html", "we-repair"),
    ("services/we-build/index.html", "we-build"),
    ("blog/index.html", "blog index"),
    ("2021/12/17/redmi-4-dead-condition/index.html", "migrated post URL"),
    ("img/uploads/2021/12/Redmi-4-Before-Dead-Condition.webp", "post image 1"),
    ("img/uploads/2021/12/Redmi-4-After-Dead-Condition.webp", "post image 2"),
])
def test_every_missing_page_is_caught(site, rel, label):
    """Each check is proven individually. A parametrised sweep is the point:
    it is what stops one assertion being deleted without the suite noticing."""
    site.drop(rel)

    out = run_smoke(site.url)

    assert out.returncode == 1, f"a missing {rel} must fail the smoke test"
    assert "SMOKE FAILED" in out.stdout
    assert label in out.stdout


def test_the_dead_form_endpoint_regression_is_caught(site):
    """The real PR #10 bug: the form posted to an endpoint that 404'd."""
    site.rewrite("contact/index.html",
                 '<html><form class="gj-contact-form" '
                 'action="https://formspree.io/f/dead"></form></html>')

    out = run_smoke(site.url)

    assert out.returncode == 1
    assert "contact form endpoint" in out.stdout


def test_the_theme_fallback_regression_is_caught(site):
    """The real PR #6/#7 bug: contact rendered the theme layout, losing the form."""
    site.rewrite("contact/index.html", "<html><body>theme fallback</body></html>")

    out = run_smoke(site.url)

    assert out.returncode == 1
    assert "contact form present" in out.stdout


def test_the_wrong_repair_figure_is_caught(site):
    """The real PR #13 bug: the homepage showed the blog-post count, not the
    lifetime total."""
    site.rewrite("index.html", "<html><body>1,500+ repairs documented</body></html>")

    out = run_smoke(site.url)

    assert out.returncode == 1
    assert "homepage repair claim" in out.stdout


def test_a_right_status_wrong_content_page_still_fails(site):
    """200-with-wrong-body is the failure a status-only check cannot see, and the
    one that let two images 404 for months while every page answered 200."""
    site.rewrite("contact/index.html", "<html>200 but empty</html>")

    out = run_smoke(site.url)

    assert out.returncode == 1
    assert "did not contain" in out.stdout


def test_an_unreachable_host_fails_rather_than_passing_silently(tmp_path):
    """CON-VER-005: 'could not reach' must not be reported as 'everything fine'.
    Port 1 on loopback refuses immediately."""
    out = run_smoke("http://127.0.0.1:1")

    assert out.returncode == 1
    assert "SMOKE FAILED" in out.stdout
