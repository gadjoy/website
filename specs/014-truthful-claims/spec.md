---
description: "Every public number traces to a source or is removed; the claim guard scans every page, not just the homepage"
status: shipped
shipped: 2026-10-31
prs: [40]
---

# Feature Specification: Truthful, Traceable Claims

**Branch**: `feat/truthful-claims` | **Date**: 2026-10-30 | **Constitution**: v2.0.0

## Problem

The site contradicts itself in public. Measured on the live site today:

| Page | Claim |
|---|---|
| Homepage hero and stats band | **15,000+** repairs since 2016 |
| `/services/we-repair/` | *"We've seen it **1,500+** times"* |

A 10× gap, both live, and that gap is *why* the numbers read as invented. Principle X says
every public number traces to a named source; `1,500+` is a literal typed into a content
file.

Three more, found by reading every claim rather than the one that was reported:

- **`★★★★★` is hard-coded twice** (`carousel.html`, `testimonials.html`), asserting a
  perfect 5.0 against a real rating of 4.7.
- **`math.Round` turns 4.7 into five stars** printed immediately beside the text "4.7".
- **"15+ Device brands serviced"** has nothing behind it. The site's own content names
  **eight**: Apple, OnePlus, Oppo, Realme, Redmi, Samsung, Vivo, Xiaomi.

### Why the existing guard missed all of it

`test_repair_claim_matches_config` is a real guard that caught PR #13's derived-figure bug.
It reads **`index.html` only**. Every contradiction above lives somewhere else, so the
suite was green throughout. The gate was correct and too narrow — the fix is scope, not
replacement.

## A dependency this surfaces

The agreed wording for the trust line leads with the verifiable numbers:

> **4.7★ from 543 Google reviews · 1,508 documented case studies**
> *15,000+ devices repaired since 2016 — around 150 a month*

**That cannot be built yet.** Review rating and count come from the Places API at build
time, and CI deliberately builds *without* `GOOGLE_PLACES_API_KEY` so the fallback path is
what gets tested. With no key there is no rating to render — which is precisely why a
hard-coded `★★★★★` sits in the fallback today.

So the review half of that line lands in **spec 015 (reviews archive)**, when
`data/reviews.json` is committed and the build reads from disk. This spec does the half it
can do honestly: remove what is unsupported, make what remains trace to a source, and widen
the guard so the next contradiction cannot hide on a non-homepage page.

## Requirements

- **FR-001** — Every public-facing number renders from `hugo.yaml`, never a literal in a
  template or content file.
- **FR-002** — `/services/we-repair/` stops contradicting the homepage. The lifetime figure
  is stated once, from config.
- **FR-003** — **"15+ device brands" is deleted.** Nothing substantiates it and the content
  names eight. An unsupported number beside true ones makes the true ones read as invented.
- **FR-004** — No hard-coded star glyphs anywhere. Where a rating is unavailable (the CI
  fallback path), the site shows **no rating at all** rather than an assumed one.
- **FR-005** — Where a rating *is* available, the stars shown must not round a 4.7 up to
  five beside the printed "4.7".
- **FR-006** — The turnaround and warranty claims move into `hugo.yaml` so they cannot
  drift between the four places they currently appear as literals.
- **FR-007** — The claim guard scans **every built page**, not `index.html`. Re-scoping a
  gate requires proving it still catches the bug it was built for (project rule), so the
  PR #13 regression test is kept and extended, never replaced.
- **FR-008** — An estimate is labelled as an estimate. `15,000+` is a lifetime figure
  derived from ~150 devices/month since 2016; it is not a counted number and must not be
  presented as one.

## Success Criteria

| # | Criterion | Coverage |
|---|---|---|
| SC-001 | No page states a repair figure that differs from `params.repairsTotal` | ✅ `test_no_page_contradicts_the_configured_repair_total` (sweeps every page) |
| SC-002 | `1,500+` appears nowhere in the built site | ✅ same; seen failing on the real `1,500+` before the fix |
| SC-003 | No hard-coded `★` glyph appears in any template | ✅ `test_no_hardcoded_star_glyphs_in_templates` |
| SC-004 | With no API key, the built site asserts no star rating | ✅ `test_the_built_site_asserts_no_rating_without_live_data` (glyph + entity forms) |
| SC-005 | A rating of 4.7 never renders as five stars | ✅ `math.Floor` + half-star; asserted by the template guard |
| SC-006 | "15+ brands" appears nowhere | ✅ `test_the_unsubstantiated_brand_count_is_gone` |
| SC-007 | Turnaround and warranty render from config on every page that states them | ✅ rendered from `params.turnaroundHours` / `warrantyDays` |
| SC-008 | The guard scans every page, and still catches the original PR #13 bug | ✅ PR #13 guard kept intact and re-proven: presenting the post count still fails it |
| SC-009 | The lifetime figure is labelled as an estimate where it appears in prose | ✅ hero renders `params.repairsBasis` + "an estimate, not a tally" |

All were OWED when written; this spec preceded the work (CON-PROC-001). The four new
guards were written against the **unfixed** tree and watched failing on the real
contradiction, the real star glyphs and the real brand count before anything was changed —
not written green after the fix.

One of them was blind on its first attempt: the brand-count check expected "15+ brands"
adjacent, but the stats band renders the number and its label in separate divs, so it
passed while the claim was live on the homepage. It now parses the rendered structure, and
`test_the_stat_parser_actually_finds_the_stats` guards that parser so the three tests built
on it cannot silently stop checking.

## Out of Scope

- The **review rating and count** in the trust line — blocked on committed review data, and
  owned by spec 015. Stated here rather than silently dropped.
- Contact-affordance duplication (spec 016) and the design system (spec 017).

## Constraints

- CI builds without `GOOGLE_PLACES_API_KEY` on purpose; the fallback path is the one under
  test, so any claim that depends on live data must degrade to **absent**, not to a
  placeholder.
- `--minify` strips attribute quotes, so any assertion over built HTML must not assume them
  — this already caused a false "meta descriptions are missing" report.
