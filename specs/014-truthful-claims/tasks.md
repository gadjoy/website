# Tasks: Truthful, Traceable Claims

> **Status: code complete; baselines and smoke pending.** Every ticked box had its guard
> seen red before the fix, or mutated afterwards. E-2 and E-3 need CI and a deploy, so they
> stay unticked until those answer — a local pass would not be evidence for either.

## Phase A — Guard
- [x] A-1 Widen the claim guard to sweep every built page (FR-007, SC-001)
- [x] A-2 Watch it fail on the current tree, on the real `1,500+` (SC-002)
- [x] A-3 Keep the PR #13 assertion intact beside it, and prove it still catches that bug (SC-008)
- [x] A-4 Test the false-positive direction, so the pattern cannot match everything

## Phase B — Unsupported claims
- [x] B-1 Delete "15+ device brands serviced" (FR-003, SC-006)
- [x] B-2 Fix the `1,500+` contradiction in `/services/we-repair/` (FR-002, SC-002)

## Phase C — Stars
- [x] C-1 Remove both hard-coded `★★★★★` blocks (FR-004, SC-003)
- [x] C-2 With no key, render no rating at all (FR-004, SC-004)
- [x] C-3 4.7 must not render as five filled stars (FR-005, SC-005)

## Phase D — Config
- [x] D-1 Turnaround and warranty into `hugo.yaml`, rendered from params (FR-006, SC-007)
- [x] D-2 Label the lifetime figure as an estimate in prose (FR-008, SC-009)

## Phase E — Verification
- [x] E-1 Full suite green; coverage floor held
- [ ] E-2 Visual baselines recaptured on the runner and reviewed (the stats band changes)
- [ ] E-3 `smoke.sh` passes against the deployed site

## Deferred — and why
The review rating and count in the trust line ("4.7★ from 543 Google reviews") need
committed review data and belong to **spec 015**. Not dropped; sequenced.
