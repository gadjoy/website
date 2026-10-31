# Tasks: One Contact System

> **Status: in progress.** Ticked only once built and the guard has been seen red
> or mutated (CON-PROC-005).

## Phase A
- [x] A-1 Region-aware affordance counter over every built page (FR-007, SC-001)
- [x] A-2 Seen failing on the current topbar duplication
- [x] A-3 Assert no `target="_blank"` on tel/mailto (FR-006, SC-006)
- [x] A-4 Assert every internal `/contact` link has its trailing slash (FR-004, SC-005)

## Phase B
- [x] B-1 Delete `menu.topbar` (FR-001)
- [x] B-2 One strapline, number clickable at every width (FR-001, SC-002)

## Phase C
- [x] C-1 Footer contact button suppressed on the contact page (FR-002, SC-003)
- [~] C-2 ~~Service pages state the CTA once~~ — **withdrawn**, see FR-003: the
      two CTAs are not duplicates, and removing the closing one would cost
      conversions
- [x] C-3 `contact_url` carries its trailing slash (FR-004)

## Phase D
- [x] D-1 Contact addresses into `hugo.yaml` (FR-005, SC-007)

## Phase E
- [x] E-1 Suite green, coverage floor held
- [ ] E-2 Baselines recaptured and reviewed
- [ ] E-3 Live site verified after deploy
