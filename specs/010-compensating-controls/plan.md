---
description: "Implementation plan for the compensating controls"
---

# Implementation Plan: Compensating Controls

**Branch**: `feat/compensating-controls` | **Date**: 2026-09-12 | **Spec**: `./spec.md`

## Summary

Three mechanisms plus one config flip, none of which need a GitHub feature the owner has
declined: a nightly canary that files an issue when `main` is red, a freshness check that
notices a stalled deploy, a merge guard that refuses to merge ahead of its checks, and the
already-present `protected_branches` gate switched on.

## Technical Context

**Language**: Python 3.13 + bash. **New dependencies: none** — `gh` is already used by
`publish_decks.py` and the Makefile; workflow YAML is already validated by the suite.

**Design constraint that shapes everything:** the interesting logic is pulled out of YAML and
bash into pure Python functions, because YAML in a scheduled workflow is the least testable code
in a repo. `decide_merge()` and `assess_freshness()` take plain data and return a verdict, so
they can be exercised without GitHub, without a cron, and without waiting a day.

## Constitution Check (v2.0.0)

- **VII. Every production bug becomes a test**: PASS — the merge guard exists because #19 and
  #21 were merged mid-flight in this repo; that is the incident it descends from.
- **VIII. Gates run in CI, not from memory**: PASS — this is that principle's backstop. The
  canary is what makes "the suite is green" a claim with a date on it.
- **IX. Verify the deployed site**: PASS — FR-002 and FR-006 extend the existing smoke into a
  scheduled check and add the staleness dimension smoke cannot see.
- **I. Test-First**: PASS — pure decision functions are written against tests first.

No violations → Complexity Tracking empty.

## Approach

### 1. `tools/merge_guard.py`
`decide_merge(checks) -> Verdict(ok, reason)`. Input is a list of `{name, state}` dicts as
`gh pr checks --json` returns them. Refuses on: any pending/queued/in-progress, any
failure/cancelled/timed-out, or an empty list (no checks configured is not "all green" — it is
the state PR #16 was in before the workflow existed).

CLI wraps it: fetch, decide, then either `gh pr merge` or exit non-zero with the reason.

### 2. `tools/deploy_freshness.py`
`assess_freshness(head_sha, deployed_sha, head_committed_at, now, grace)`. Equal shas → fresh.
Different but inside the grace window → in-flight, not a failure. Different and older than the
grace window → stale, which is the "deploy quietly stopped" signal.

Grace defaults to 6h: long enough that a queued Pages deploy or a slow morning never cries wolf,
short enough that a stall is caught the same day.

### 3. `.github/workflows/canary.yml`
`schedule: cron` daily plus `workflow_dispatch`. Runs the suite, the smoke script, and the
freshness check; on any failure files an issue, reusing an open one if present (FR-004) and
closing it when the canary next passes (FR-005). Issue identity is a fixed title prefix plus a
label, so the lookup is a search rather than state stored anywhere.

### 4. `.house-gates.json`
`protected_branches: ["main"]`. One line, and `check_hygiene.py` already implements the check —
it shipped switched off with a note saying to turn it on.

## Key risks

- **Cron noise.** Mitigated by FR-004/FR-005: at most one open canary issue at a time.
- **A canary that fails for its own reasons** (rate limit, runner outage) would cry wolf. The
  issue body names which of the three checks failed, so a flaky-infrastructure failure is
  distinguishable from a real red `main` at a glance.
- **`protected_branches` blocking legitimate work.** `HOUSE_GATES_SKIP=1` is the documented
  escape hatch, already supported by the hook.

## Validation: mutation testing

Each guard was neutered in turn and its test required to fail — a guard never seen to fail is a
guess, and two guards in PR #14 passed vacuously before being checked this way.

| Mutation | Result |
|---|---|
| Merge guard treats pending as green | caught |
| Merge guard treats "no checks" as green | caught |
| Freshness loses the grace period (cries wolf on in-flight deploys) | caught |
| Freshness never reports staleness | caught |
| Canary stops de-duplicating issues | caught |
| Local branch guard switched back off | caught |

Also exercised against the live repo rather than only in unit tests: freshness correctly reports
`deployed commit matches main (f57570f2)`; the merge guard allows #21 (4 checks green, exit 0)
and refuses #17 (no checks, exit 1).

One test was changed rather than the code: it originally asserted the canary used
`if: failure()`. The implementation uses `continue-on-error` plus a report step that evaluates
every outcome, so the issue can name *all* failures instead of stopping at the first. The test
had encoded an implementation detail rather than the requirement, and now asserts the
requirement.

## Phases

- **A**: pure decision functions + their tests (RED → GREEN)
- **B**: CLI wrappers, canary workflow, Makefile target
- **C**: enable the house-gates branch guard
- **D**: mutation-test every guard, then ship

## Complexity Tracking

*No constitution violations — section intentionally empty.*
