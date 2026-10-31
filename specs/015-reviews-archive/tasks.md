# Tasks: Reviews Archive

> **Status: in progress.** Ticked once built and the guard has been seen red or
> mutated (CON-PROC-005).

## Phase A — The archive
- [x] A-1 `tools/fetch_reviews.py`, writing `data/reviews.json` (FR-001)
- [x] A-2 Union-merge by review id; a smaller response never shrinks it (FR-007, SC-006)
- [x] A-3 Payload validated before any write
- [x] A-4 Archive records retrieved-vs-total and why (FR-006, SC-007)

## Phase B — Build reads disk
- [x] B-1 `testimonials.html` reads `data/reviews.json`, no network (FR-002, SC-002)
- [x] B-2 Rating filter removed; criticism published (FR-003, SC-003)
- [x] B-3 Trust line shows archived rating and count (FR-008, SC-008)

## Phase C — Publish
- [x] C-1 `/testimonials/` listing every archived review (FR-004, SC-004)
- [x] C-2 `LocalBusiness` + `AggregateRating` JSON-LD from the same file (FR-005, SC-005)

## Phase D — Verification
- [x] D-1 Suite green, coverage floor held
- [x] D-2 Real fetch run in CI, output reviewed, archive committed
- [ ] D-3 JSON-LD validated
- [ ] D-4 Baselines recaptured

## Blocked on the owner
- [ ] OAuth for the Business Profile API — the other ~544 reviews. The pipeline
      is built so this needs no template change when it lands.
