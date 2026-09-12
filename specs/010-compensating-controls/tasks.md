---
description: "Task list for the compensating controls"
---

# Tasks: Compensating Controls

> **Status: COMPLETE and verified in production.** `pytest` **166 passed**; all six guards
> mutation-tested (6/6 caught); and every control exercised against the live repo:
>
> | Control | Real-world proof |
> |---|---|
> | Canary | Dispatched run **34695820363** green: suite, smoke, freshness, report all passed |
> | Issue filing | Simulated failure filed **#23** and exited 1 (FR-003) |
> | Dedup | Second failure commented on #23 rather than opening a second issue (FR-004) |
> | Auto-close | Returning to green closed #23 automatically (FR-005) |
> | Merge guard | Refused **#22** while its own checks ran (`exit 1`), then merged it when green |
> | Freshness | `deployed commit matches main (f57570f2)` against the live repo |
> | Branch guard | A real `git commit` on `main` was **blocked by the hook**; HEAD unchanged |
>
> The issue paths were proven by extracting the Report step *from the shipped workflow* and
> running it with simulated step outcomes, so the logic tested is the logic that ships — not a
> copy that could drift.

**Input**: `specs/010-compensating-controls/{spec,plan}.md` | **Constitution**: v2.0.0

---

## Phase A: Decision logic, test-first

- [x] T001 Write `test_compensating_controls.py` against `decide_merge` and
      `assess_freshness`; confirm RED (no module yet).
- [x] T002 `decide_merge`: refuse pending, refuse failing, refuse empty, allow all-green.
- [x] T003 `assess_freshness`: fresh when equal; in-flight inside grace; stale beyond grace.
- [x] T004 Implement `tools/merge_guard.py` + `tools/deploy_freshness.py` until GREEN.

## Phase B: Wiring

- [x] T005 CLI for the merge guard: fetch checks, decide, merge or exit non-zero with reason.
- [x] T006 `.github/workflows/canary.yml` — daily cron + `workflow_dispatch`; suite, smoke,
      freshness; file an issue on failure, reuse an open one, close it when green again.
- [x] T007 `make merge PR=n` and `make canary`.
- [x] T008 Test the workflow's shape: valid YAML, has a schedule, invokes suite + smoke.

## Phase C: Local branch guard

- [x] T009 Set `protected_branches: ["main"]` in `.house-gates.json`.
- [x] T010 Test that a commit on `main` is refused and one on a branch is allowed.

## Phase D: Prove the guards

- [x] T011 Mutation-test: neuter each guard in turn and confirm its test fails.
- [x] T012 Full suite green; update the spec coverage table and `specs/README.md`.

---

## Deferred

- [ ] D001 Alerting beyond a GitHub issue (email/SMS). The issue is the channel; routing is a
      notification setting, not code.
- [ ] D002 Automatic revert when the canary goes red. Detection first — auto-revert on an
      unprotected repo is a way to lose work.
