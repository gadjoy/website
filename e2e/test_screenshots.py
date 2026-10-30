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

        # Scroll the whole page first. Scroll-triggered reveals and
        # loading="lazy" images only resolve once they have been near the
        # viewport, and a full-page screenshot does not reliably trigger them.
        pg.evaluate("""() => new Promise(resolve => {
            let y = 0;
            const step = () => {
                y += window.innerHeight;
                window.scrollTo(0, y);
                if (y < document.body.scrollHeight) { setTimeout(step, 40); }
                else { window.scrollTo(0, 0); setTimeout(resolve, 120); }
            };
            step();
        })""")

        # Freeze everything that makes a capture non-deterministic, and FORCE
        # the revealed end-state. The theme ships animate.css, whose classes
        # set visibility:hidden until a reveal fires — so disabling animation
        # alone can freeze an element in its HIDDEN state instead of its final
        # one. That is not theoretical: one card on /services/we-build/ was
        # present in one capture and absent in the next, a 0.537% diff against
        # a 0.200% budget, with every other pixel identical.
        #
        # The fix is to make the capture deterministic, NOT to raise the
        # budget. Raising it to swallow a real missing element is how a visual
        # gate quietly stops being one.
        pg.add_style_tag(content="""
            /* FINISH animations instantly; do NOT cancel them.
             *
             * `animation: none` looks like the obvious way to freeze a page,
             * and it is wrong here. custom.css starts the hero elements and
             * every stats tile at `opacity: 0` and relies on
             * `animation: gadjoyUp .7s forwards` to reveal them. Cancelling the
             * animation strands them at opacity 0 — so the homepage baselines
             * captured a BLANK hero and a BLANK stats band, and the visual gate
             * was blind to the most important part of the page while reporting
             * success.
             *
             * A near-zero duration lets `forwards` animations land on their end
             * state, which is what a user sees. */
            *, *::before, *::after {
                animation-duration: 0.001s !important;
                animation-delay: 0s !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.001s !important;
                transition-delay: 0s !important;
                caret-color: transparent !important;
            }
            /* Scroll-reveal libraries hide via visibility/opacity until a
             * class is added by JS, which a near-zero duration cannot help. */
            .animated, [class*="animate"], [class*="wow"], [data-aos] {
                opacity: 1 !important;
                visibility: visible !important;
                transform: none !important;
            }
            html { scroll-behavior: auto !important; }
        """)
        pg.wait_for_load_state("networkidle")
        pg.wait_for_timeout(400)

        # Assert the freeze did not hide anything. Everything above exists to
        # make the capture deterministic; none of it is allowed to make the
        # capture WRONG. This is checked on the page itself rather than by
        # eyeballing the PNG, because a blank hero on a long page looks like
        # whitespace.
        hidden = pg.evaluate("""() => {
            const out = [];
            for (const sel of ['.gadjoy-hero h1', '.gadjoy-stats .stat',
                               '.gadjoy-trust', '.hero-art']) {
                for (const el of document.querySelectorAll(sel)) {
                    // Skip anything NOT LAID OUT at this breakpoint. The hero
                    // art sits in a `hidden-xs` column, so on mobile it is
                    // display:none by design — absent, not invisible. Flagging
                    // it would make this guard cry wolf at 390px, and a guard
                    // that cries wolf gets deleted. The bug shape being caught
                    // is "takes up space but cannot be seen".
                    const box = el.getBoundingClientRect();
                    if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') continue;
                    if (box.width === 0 || box.height === 0) continue;

                    const cs = getComputedStyle(el);
                    if (parseFloat(cs.opacity) < 0.9 || cs.visibility === 'hidden') {
                        out.push(sel + ' opacity=' + cs.opacity +
                                 ' visibility=' + cs.visibility);
                    }
                }
            }
            return out;
        }""")
        assert not hidden, (
            f"{page_name}/{vp_name}: the capture froze content INVISIBLE: "
            f"{hidden}. The baseline would record a blank region and the visual "
            f"gate would be blind to it. Make animations finish, never cancel "
            f"them.")
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
