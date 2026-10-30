# Implementation Plan: Truthful, Traceable Claims

**Spec**: [spec.md](spec.md) | **Date**: 2026-10-30

## Order

The widened guard lands **first**, red, against the current site. That is the only way to
know it actually catches today's contradiction rather than merely passing once the content
is fixed — a gate written after the fix has never been red (CON-PROC-005).

Then the content and template changes turn it green.

## Phase A — Widen the guard, and watch it fail

`test_repair_claim_matches_config` reads `index.html`. The contradiction lives in
`/services/we-repair/`, so it was invisible.

**Re-scoping a gate carries an obligation here**: ship a test proving it still catches the
bug it was built for. `test_gate_scoping.py` is the in-repo precedent and this follows it —
the PR #13 assertion (the blog-post count must never be presented as a repair statistic) is
kept intact and the page sweep is added beside it, so neither can be lost by editing the
other.

The sweep walks every built HTML page for figures that look like repair counts and asserts
each equals `params.repairsTotal`. Written to fail on the current tree.

## Phase B — Remove what is unsupported

Deleting "15+ device brands" is the right call rather than finding a number that fits. The
content names eight; writing "8+" to make the stat survive would be reverse-engineering a
claim to keep a slot filled, which is the same failure in a smaller font.

The stats band then has three entries rather than four. That is fine — three true numbers
beat four with one invented.

## Phase C — Stars

Two distinct bugs that look like one:

1. **Hard-coded `★★★★★`** asserts 5.0 from nothing. In the CI fallback path there is no
   rating at all, so the honest render is *nothing* — not a placeholder, and not an
   averaged guess (CON-DATA-001: a field nobody looked at is information).
2. **`math.Round(4.7)` = 5** prints five filled stars next to the text "4.7", which reads
   as a typo in the number rather than a rounding choice. `math.Floor` plus a half-star is
   the fix, and the assertion is that a 4.7 never yields five filled glyphs.

## Phase D — Literals into config

`24h` turnaround and `90-day` warranty appear as literals in four places. They agree today,
which is luck. Into `hugo.yaml`, rendered from params, asserted by the sweep.

## Risks

- **The sweep could be too eager** and flag an unrelated number — a price, a model number,
  a year. Scoped to figures adjacent to repair vocabulary, and the false-positive direction
  is tested explicitly so the pattern cannot quietly match everything.
- **Visual baselines will change.** The stats band loses an entry and the stars change.
  That is a real rendering change, so the baselines get recaptured on the runner and
  reviewed — not force-updated to silence the gate.
