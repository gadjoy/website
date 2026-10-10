# Tasks: Progressive Web App

> **Status: built; one item awaiting CI.** Every ticked box had its guard mutated and seen
> to fail (CON-PROC-005). D-5 stays unticked until CI confirms it: the visual baselines are
> environment-specific and SKIP on this box, so a local pass would not be evidence.

## Phase A — Icons
- [x] A-1 Script that pads the brand logo to square 192² and 512² (FR-002)
- [x] A-2 Separate maskable icon with safe-zone padding, not the standard icon relabelled
- [x] A-3 Test asserting dimensions, squareness and that maskable differs from standard

## Phase B — Manifest
- [x] B-1 Hugo-generated manifest reading `hugo.yaml` (FR-001, FR-003)
- [x] B-2 Test asserting it is valid JSON, served, and traces to `hugo.yaml` (SC-001)
- [x] B-3 Test asserting declared icons exist on disk at the declared sizes (SC-002)

## Phase C — Service worker
- [x] C-1 `static/sw.js`: versioned caches, app-shell precache (FR-004, FR-005, FR-009)
- [x] C-2 Network-first HTML, cache-first assets (FR-006, SC-010)
- [x] C-3 Offline page carrying address, phone, WhatsApp, hours (FR-007, SC-007)
- [x] C-4 POST and cross-origin never intercepted (FR-008, SC-008)
- [x] C-5 Registration partial, guarded, after load (FR-004)
- [x] C-6 Old-version caches deleted on activate (SC-009)

## Phase D — Verification
- [x] D-1 e2e: SW registers and activates at root scope (SC-004)
- [x] D-2 e2e: visited page renders offline (SC-005)
- [x] D-3 e2e: unvisited page shows the Gadjoy offline page, not a browser error (SC-006)
- [x] D-4 e2e: installability criteria met (SC-003)
- [ ] D-5 Visual baselines still pass (SC-011, FR-010)

## Deferred
Nothing. Push notifications and background sync are **out of scope**, not deferred — they
need a backend that does not exist. See the spec.
