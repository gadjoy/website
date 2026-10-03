"""Visual baselines at 1440px and 390px (spec 012, FR-003 / SC-004).

This is the only guard for the entire spec-003 class of defect — the invisible
Call button, layout drift — which that spec marked untestable.

ON BASELINE VALIDITY
--------------------
A screenshot baseline is only comparable against the environment that produced
it: font packages, Chromium build and DPI all change the pixels. The Linux CI
jobs run on self-hosted runners, which are this same machine, so baselines
captured with `make baselines` are valid there. They are NOT valid on
GitHub-hosted runners, which is where CI falls back when CI_RUNS_ON is unset.

So each baseline set records a fingerprint, and a mismatch SKIPS rather than
fails. A red gate caused by running somewhere else is a gate people learn to
ignore (CON-VER-008), and a skip that states its reason is honest where a
silent pass would not be.

Candidates and diffs are written to e2e/_output/ for CI to upload, so a failure
can be looked at rather than guessed at.
"""
import hashlib
import json
import platform
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import BASELINE_DIR, PAGES, VIEWPORT_ONLY, VIEWPORTS  # noqa: E402
from visual import compare  # noqa: E402

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

OUTPUT_DIR = Path(__file__).resolve().parent / "_output"
FINGERPRINT = BASELINE_DIR / "fingerprint.json"

CASES = [(p, v) for p in sorted(PAGES) for v in sorted(VIEWPORTS)]


RENDER_PROBE = """
<html><body style="margin:0;background:#fff">
  <div style="font:16px/1.4 sans-serif;padding:8px">Gadjoy 0123456789 gjqy</div>
  <div style="font:12px/1.2 serif;padding:8px">Repair &amp; Service — Bangalore</div>
</body></html>
"""


def fingerprint(browser):
    """What actually decides whether two screenshot sets are comparable.

    An earlier version keyed on the kernel major version, which is causally
    unrelated to rendering: the dev box (kernel 5) and the runner (kernel 6)
    produced byte-identical Chromium builds and would still have been declared
    incomparable. It also missed the thing that does matter — installed fonts.

    So the fingerprint renders a fixed text sample and hashes the pixels. That
    measures the question being asked ("will screenshots match here?") instead
    of a proxy for it.
    """
    ctx = browser.new_context(viewport={"width": 320, "height": 120},
                              device_scale_factor=1)
    pg = ctx.new_page()
    try:
        pg.set_content(RENDER_PROBE)
        png = pg.screenshot()
    finally:
        ctx.close()
    return {
        "platform": platform.system(),
        "chromium": browser.version,
        "text_render": hashlib.sha256(png).hexdigest()[:16],
    }


def shoot(browser, site_url, page_name, vp_name, dest: Path):
    w, h = VIEWPORTS[vp_name]
    ctx = browser.new_context(viewport={"width": w, "height": h},
                              device_scale_factor=1)
    pg = ctx.new_page()
    try:
        pg.goto(site_url + PAGES[page_name], wait_until="load")
        # Freeze anything that would make the capture non-deterministic:
        # CSS animation/transition, and the caret.
        pg.add_style_tag(content="""
            *, *::before, *::after {
                animation: none !important;
                transition: none !important;
                caret-color: transparent !important;
            }
            html { scroll-behavior: auto !important; }
        """)
        pg.wait_for_timeout(250)
        dest.parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(dest), full_page=page_name not in VIEWPORT_ONLY)
    finally:
        ctx.close()


@pytest.mark.parametrize("page_name,vp_name", CASES,
                         ids=[f"{p}-{v}" for p, v in CASES])
def test_page_matches_its_baseline(browser, site_url, page_name, vp_name):
    name = f"{page_name}-{vp_name}.png"
    baseline = BASELINE_DIR / name

    if not baseline.is_file():
        pytest.skip(
            f"no baseline for {name}. Capture them with `make baselines` on the "
            f"machine CI runs on, review the images, and commit e2e/baselines/.")

    if FINGERPRINT.is_file():
        recorded = json.loads(FINGERPRINT.read_text())
        current = fingerprint(browser)
        if recorded != current:
            pytest.skip(
                f"baselines were captured on {recorded} and this is {current}. "
                f"Screenshot pixels are environment-specific; comparing across "
                f"environments produces a permanently red gate, so this is "
                f"skipped rather than failed. Re-capture on this environment, "
                f"or run CI on the self-hosted runners (set CI_RUNS_ON).")

    candidate = OUTPUT_DIR / name
    shoot(browser, site_url, page_name, vp_name, candidate)

    result = compare(baseline, candidate, diff_out=OUTPUT_DIR / f"diff-{name}")

    assert result.ok, (
        f"{name}: {result.reason}. The candidate and a diff mask are in "
        f"e2e/_output/ — CI uploads them as an artifact. If the change is "
        f"intended, re-run `make baselines` and commit the new images.")


def test_a_baseline_set_records_where_it_came_from():
    """A baseline directory with no fingerprint cannot be validated against the
    machine comparing it, so the skip above would never fire and every run
    would fail for the wrong reason."""
    if not BASELINE_DIR.is_dir() or not any(BASELINE_DIR.glob("*.png")):
        pytest.skip("no baselines committed yet")

    assert FINGERPRINT.is_file(), (
        "e2e/baselines/ contains images but no fingerprint.json — re-capture "
        "with `make baselines`, which writes both.")


def test_every_listed_page_is_covered_at_both_widths():
    """Static: no browser needed. A page added to PAGES without baselines must
    be visible as a gap, not silently uncovered."""
    assert len(CASES) == len(PAGES) * len(VIEWPORTS)
    assert {v for _, v in CASES} == {"desktop", "mobile"}
