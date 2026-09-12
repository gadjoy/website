---
description: "Detect a red main and a stalled deploy without branch protection: nightly canary, fail-loud, merge guard"
status: in-progress
prs: [22]
---

# Feature Specification: Compensating Controls for an Unprotected `main`

**Branch**: `feat/compensating-controls` | **Date**: 2026-09-12 | **Constitution**: v2.0.0

## Problem

Branch protection is not going to be enabled, so `test` can never be a *required* status check.
The question is what that actually leaves exposed, and the honest answer is narrower than it
sounds:

`build` declares `needs: test`, `deploy` needs `build`, `smoke` needs `deploy`. **A red suite
already cannot reach gadjoy.in.** Deployment safety does not depend on branch protection.

What is genuinely missing is *detection and merge discipline*:

1. **A red `main` is invisible.** If `test` fails on a push to `main`, the deploy simply stops.
   The site keeps serving the last good build, so nothing looks broken — it just silently stops
   updating. Nobody is told. This repo has already lived through exactly that: the suite was red
   on `main` for two months while PR descriptions truthfully reported it green.
2. **Nothing stops a merge landing before its checks finish.** Not hypothetical — PRs #19 and
   #21 were both merged in this repo while their checks were still running. It happened to be
   harmless; the mechanism that allowed it is not.
3. **Nothing notices a deploy that has quietly stopped.** "Stale but serving 200" is the failure
   mode a smoke test cannot see, because every page it checks still answers correctly.

PR #20 installed local pre-commit hooks (secret scanning, commit-message format), covering
prevention on the authoring machine. It does not cover any of the three above.

## User Scenarios

### US1 — A red `main` surfaces within a day, not a quarter (P1)
The suite breaks on `main`. Within 24 hours an issue exists saying so, naming the commit.

### US2 — A merge cannot jump ahead of its checks (P1)
Someone merges a PR whose checks are still running or already failing. The tooling refuses and
says why, rather than merging and hoping.

### US3 — A deploy that stops is noticed (P2)
The pipeline stops deploying — a stuck run, a broken build, a revoked permission. Detected and
reported, rather than the site silently ageing.

### US4 — Committing straight to `main` is blocked locally (P2)
`.house-gates.json` already supports this and ships with it disabled. Turning it on gives a
local equivalent of "work goes on a branch" — the part of branch protection that is achievable
without the feature.

## Requirements

- **FR-001** A scheduled workflow MUST run the acceptance suite against `main` at least daily,
  independent of any push.
- **FR-002** It MUST also run `scripts/smoke.sh` against the live origin, so a site that breaks
  without a deploy (DNS, certificate, Pages outage) is caught.
- **FR-003** On failure it MUST open a GitHub issue naming what failed and the commit it failed
  on. Console-only failure is not detection — nobody reads a green-by-default runs list.
- **FR-004** It MUST NOT open a duplicate issue when one is already open for the same failure.
  A daily cron filing 90 identical issues trains people to ignore it.
- **FR-005** It MUST close the issue automatically when the canary next passes, so the issue
  list reflects current state rather than history.
- **FR-006** The deploy-freshness check MUST compare the last successful deploy's commit against
  `main`'s HEAD, and MUST fail only when `main` is *ahead* and has been for longer than a grace
  period — a deploy in progress is not a stalled deploy.
- **FR-007** A merge guard MUST refuse to merge a pull request whose checks are pending, failing,
  or absent, and MUST state which.
- **FR-008** The guard's decision MUST be a pure function of the check states, so it is testable
  without GitHub.
- **FR-009** The guard MUST be reachable as a single command (`make merge PR=n`).
- **FR-010** Local commits directly to `main` MUST be blocked by enabling the
  `protected_branches` gate that `.house-gates.json` already supports.

## Success Criteria

| ID | Criterion | Test coverage |
|---|---|---|
| SC-001 | Canary workflow is valid YAML, runs on a cron, and invokes suite + smoke | ✅ `test_canary_workflow_is_valid_and_scheduled`, `test_canary_runs_the_suite_and_the_smoke_test` |
| SC-002 | Merge guard refuses on pending, failing, and no-checks; allows only all-green | ✅ `test_all_green_is_allowed`, `test_pending_checks_are_refused`, `test_every_bad_state_is_refused`, `test_no_checks_at_all_is_refused` |
| SC-003 | Freshness passes when deployed == HEAD, and when behind but inside the grace period | ✅ `test_deployed_head_is_fresh`, `test_recent_commit_not_yet_deployed_is_in_flight` |
| SC-004 | Freshness fails when `main` has been ahead beyond the grace period | ✅ `test_commit_undeployed_beyond_the_grace_period_is_stale`, `test_grace_boundary_is_not_off_by_one` |
| SC-005 | Issue filing is idempotent — an existing open canary issue is reused, not duplicated | ✅ `test_canary_does_not_spam_duplicate_issues` |
| SC-006 | `protected_branches` is `["main"]`, and a commit on `main` is blocked | ✅ `test_house_gates_protects_main`, `test_hygiene_check_actually_refuses_a_commit_on_main` |
| SC-007 | Every guard fails when its bug is reintroduced (mutation-tested) | ✅ mutation-tested — 6 of 6 guards fail when neutered (see plan.md → Validation) |

## Out of Scope

- **Branch protection / rulesets.** Declined by the owner; this feature exists because of that.
- **Auto-merge.** `allow_auto_merge` is `false`, and with no required checks GitHub may treat
  "nothing required" as satisfied and merge immediately — the opposite of what is wanted. The
  merge guard is the deterministic version.
- **Paging or external alerting.** A GitHub issue is the channel; routing is the owner's
  existing notification settings.
- **Automatic revert of a bad commit.** Detection first. Auto-revert on an unprotected repo is a
  way to lose work.
