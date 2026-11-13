"""No element on a key page renders in Roboto (spec 020, FR-005 / SC-006).

Roboto came from the theme: its class selectors (.btn, .label, .breadcrumb,
.pagination …) out-rank custom.css's element selectors, so 46 elements across
seven pages kept the theme's typeface while everything around them was Inter.
Measured from computed style, not from the stylesheet, because the question is
what the browser chose — and once Roboto is no longer linked, a selector still
naming it renders in Helvetica/Arial instead, which no stylesheet test would see.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import PAGES  # noqa: E402

pytest.importorskip("playwright.sync_api", reason="playwright not installed")


@pytest.mark.parametrize("name,path", sorted(PAGES.items()))
def test_no_element_renders_in_roboto(page, site_url, name, path):
    page.goto(site_url + path, wait_until="domcontentloaded")
    offenders = page.evaluate("""() => {
        const out = [];
        for (const el of document.querySelectorAll('body *')) {
            if (!el.childNodes.length || !el.getClientRects().length) continue;
            const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
            if (!hasText) continue;
            const first = getComputedStyle(el).fontFamily.split(',')[0].replace(/["']/g, '').trim();
            if (first.toLowerCase() === 'roboto') {
                out.push(el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).trim().split(/\\s+/).join('.') : ''));
            }
        }
        return out;
    }""")
    assert not offenders, f"{path}: {len(offenders)} elements in Roboto, e.g. {sorted(set(offenders))[:8]}"
