# Tasks: Self-Hosted Fonts

> **Status: complete.** Every guard seen red first; two mutants applied and failed.

## Step 1 — self-host, value-preserving

- [x] T-1 Font tests seen red with the change absent (SC-001..SC-004)
- [x] T-2 Nine woff2 files + `fonts.css`, linked before `custom.css`; `@import` and preconnects removed (FR-001, FR-002)
- [x] T-3 Mutants applied and failed: a missing file, a missing weight (FR-003)
- [x] T-4 e2e comparison green against unchanged baselines (SC-005). Two runs each compared
      13 of 14 pages: the 14th skipped because the probe's OWN Google Fonts fetch raced
      (fingerprint `c83d…` vs `51c3…`), which -rs exposed. T-7 removes that race; the
      step-2 recapture's fingerprint is unchanged (`51c385ca1b02e4db`), confirming the
      self-hosted bytes draw the same pixels.

## Step 2 — retire Roboto, intended change

- [x] T-5 `test_no_element_renders_in_roboto` seen red: 7 of 7 pages (SC-006)
- [x] T-6 Override the theme's Roboto selectors; drop the Roboto link (FR-004)
- [x] T-7 Fingerprint probe renders the self-hosted files (FR-006)
- [x] T-8 Recaptured on CI (run 43586165124). Every page moved < 0.21%; regions changed
      are button labels and stat captions only, inspected side by side (SC-007).
