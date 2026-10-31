# Tasks: Design System & Two Dead Pages

> **Status: in progress.** Ticked once built and the guard seen red or mutated.

## Phase A — The dead pages
- [x] A-1 `/services/` lists the services (FR-003, SC-003, SC-004)
- [x] A-2 The homepage renders `_index.md`'s body (FR-004, SC-005)

## Phase B — Tokens
- [x] B-1 Shadow, radius and grey tokens on `:root` (FR-001)
- [x] B-2 Existing literals collapsed onto them, value-preserving (SC-001)
- [x] B-3 WhatsApp number declared once (FR-002, SC-002)

## Phase C — Sharing
- [x] C-1 Open Graph + Twitter tags (FR-005, SC-006, SC-007)
- [x] C-2 Page titles carry the business name (FR-006, SC-008)

## Phase D — Verification
- [x] D-1 Suite green, coverage held
- [ ] D-2 Baselines prove the token pass changed nothing visually

## Deferred, with reason
One `page-hero.html`, one `.section-title`, one `.gj-card`: large refactors of
working markup whose visible outcome is "identical, but tidier". Tokens first
makes them mechanical later. See the plan.
