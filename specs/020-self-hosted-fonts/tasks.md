# Tasks: Self-Hosted Fonts

> **Status: in progress.** Step 1 is on the PR; step 2 follows its e2e result.

## Step 1 — self-host, value-preserving

- [x] T-1 Font tests seen red with the change absent (SC-001..SC-004)
- [x] T-2 Nine woff2 files + `fonts.css`, linked before `custom.css`; `@import` and preconnects removed (FR-001, FR-002)
- [x] T-3 Mutants applied and failed: a missing file, a missing weight (FR-003)
- [ ] T-4 e2e comparison green against unchanged baselines, every page compared, none skipped (SC-005)

## Step 2 — retire Roboto, intended change

- [x] T-5 `test_no_element_renders_in_roboto` seen red: 7 of 7 pages (SC-006)
- [ ] T-6 Override the theme's Roboto selectors; drop the Roboto link (FR-004)
- [ ] T-7 Fingerprint probe renders the self-hosted files (FR-006)
- [ ] T-8 Recapture baselines on CI's image; describe the change (SC-007)
