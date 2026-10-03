---
description: "End-to-end journeys, visual baselines, entry-point checks, and the CI security gates the fleet constitution requires"
status: in-progress
---

# Feature Specification: End-to-End Verification & Security Gates

**Branch**: `feat/e2e-and-security-gates` | **Date**: 2026-10-03 | **Constitution**: v2.0.0

## Problem

Unit coverage reached 95.10% in #34. That number says nothing about whether the site works,
and the constitution is explicit about why: CON-COV-001 records a project sitting at 97%
while *every* production incident lived in code no suite touched.

This repo's own history is the same shape. Every recent user-visible defect was found by a
human looking at gadjoy.in, not by a test:

| Defect | What the suite said |
|---|---|
| Contact page fell back to the theme layout | green |
| Enquiry form posted to a dead endpoint | green |
| Two images 404'd in production for two months | green — `Path.exists()` is case-insensitive on macOS |
| Homepage says 15,000+ repairs, `/services/we-repair/` says 1,500+ | green |
| Call button invisible at some widths (`003`) | marked **untestable** |

Each of those is reachable from a browser in under ten seconds. None was reachable from
`pytest` as it stood.

Separately, four fleet rules landed in the shared constitution after this repo was last
audited, and gadjoy meets none of them:

- **CON-SEC-002** — dependency scanning *and* full git-history secret scanning as CI gates.
  This repo has neither, and it has carried a `.wpress` backup and 15,554 `wp-export` files,
  so the history scan is not theoretical here.
- **CON-SEC-003** — audit the shipped tree and the build tree separately; trace what actually
  ships rather than trusting a tool's own split.
- **CON-SEC-004** — declare the security headers a deployed surface sends, and assert them.
  GitHub Pages **cannot set headers**; the rule's named failure is staying silent about that,
  not the absence itself.
- **CON-VER-008** — a test that fails only in the full run is a red gate, not noise. With
  seven runners on four vCPUs, suites here will run under load.

## User Scenarios

### US1 — A customer can get from the homepage to a phone number (P1)
Someone lands on gadjoy.in, opens a repair post, reaches the contact page and submits an
enquiry. Every step is asserted in a real browser, not by matching markup.

### US2 — A layout regression is caught before deploy, not by eye (P1)
A CSS or layout change shifts the page. CI shows the visual difference and fails, instead of
the change reaching a live business site and being noticed later.

### US3 — A broken entry point is caught in CI (P2)
A script in `tools/` or `migration/scripts/` stops being runnable. CI catches it, rather than
the next person to run it at the moment they need it.

### US4 — A dependency advisory or a leaked secret fails the build (P1)
Not a dashboard nobody reads (CON-SEC-002).

### US5 — The site's security posture is written down (P2)
Including, and especially, what the hosting platform makes impossible.

## Requirements

### End-to-end
- **FR-001** — Playwright drives Chromium against a locally built site. Chromium runs
  **directly on the self-hosted runner**, no container: verified working on this Ubuntu 20.04
  box with Playwright 1.60.0, and trailward already does exactly this in CI.
- **FR-002** — A journey test covers homepage → repair post → contact, asserting
  **rendered, interactive** state: the element is visible, in the viewport, and clickable.
- **FR-003** — Every page is captured at **1440px and 390px**. Baselines are committed; CI
  fails on an unexpected diff and publishes the before/after as an artifact.
- **FR-004** — The enquiry form's submit path is asserted against an intercepted request, so
  "posts to a dead endpoint" is detectable without sending real mail.
- **FR-005** — Visual comparison tolerates antialiasing noise but not layout movement. The
  threshold is stated in the spec and asserted by a test that moves an element and watches
  the comparison fail.

### Entry points
- **FR-006** — Every executable entry point in `tools/` and `migration/scripts/` answers
  `--help` with exit 0 in CI. Scripts excluded from this are named with a reason.
- **FR-007** — Every entry point that writes anything supports `--dry-run`, and the dry run
  is asserted to leave the tree unchanged.
- **FR-008** — `scripts/smoke.sh` has a self-test against a fixture server, so the smoke test
  itself cannot silently stop checking.

### Security gates
- **FR-009** — Dependency scanning runs in CI and **fails** at a stated severity.
- **FR-010** — Secret scanning covers the **full git history**, not just the diff, and fails
  the build.
- **FR-011** — The shipped tree (`public/`) and the build tree (toolchain, CI) are audited
  **separately**, and a finding in the build tree is never waved away as "not shipped"
  (CON-SEC-003).
- **FR-012** — `SECURITY.md` states the headers the site sends, **and records that GitHub
  Pages cannot set response headers**, naming what the platform does allow instead. A test
  asserts the declaration matches what the live site actually returns.

### Suite integrity
- **FR-013** — The suite runs under a second `PYTHONHASHSEED` in CI, so an ordering
  dependency fails loudly rather than intermittently (CON-VER-008, resumefit precedent).

## Success Criteria

| # | Criterion | Coverage |
|---|---|---|
| SC-001 | The full journey passes against a real built site | ✅ `e2e/test_journeys.py::test_homepage_to_post_to_contact` |
| SC-002 | Moving a page element by 10px fails the visual comparison | ✅ `e2e/test_visual_compare.py::test_a_ten_pixel_shift_fails` |
| SC-003 | Antialiasing differences alone do not fail it | ✅ `test_antialiasing_scale_noise_passes`, `test_a_faint_edge_softening_passes` |
| SC-004 | Every page has a committed baseline at both widths | ✅ `e2e/test_screenshots.py` (14 baselines; skips off-environment, by design) |
| SC-005 | A form posting to a dead endpoint is detected | ✅ `test_the_form_posts_to_the_live_endpoint` |
| SC-006 | Every entry point answers `--help` with exit 0 | ✅ `migration/tests/test_entry_points.py` |
| SC-007 | Every `--dry-run` leaves the working tree byte-identical | ✅ `test_publish_decks_dry_run_writes_nothing` + per-tool dry-run tests |
| SC-008 | `smoke.sh` fails against a fixture server serving a broken page | ✅ `migration/tests/test_smoke_selftest.py` (15 cases) |
| SC-009 | A known-vulnerable dependency fails CI | ✅ `security.yml` → `pip-audit`, plus a non-vacuity check |
| SC-010 | A secret committed anywhere in history fails CI | ✅ `test_a_project_scoped_openai_key_is_caught` |
| SC-011 | `SECURITY.md`'s header claims match the live response | ✅ `migration/tests/test_security_posture.py` |
| SC-012 | The suite passes under two different hash seeds | ✅ `hugo.yml` two-seed matrix; both seeds verified green locally |

Every criterion was OWED when this spec was written, which preceded the work
(CON-PROC-001). The coverage column was filled in only as each guard was built **and
mutated to confirm it can fail** — a green test that has never been red is not evidence
(CON-PROC-005).

Two things this does **not** cover, stated rather than implied: a layout break below the
fold on `/gallery/` or `/blog/` (captured at viewport height, because full-page baselines
of editorial pages churn on every new post), and a horizontal rule sliding along its own
axis (a limit of pixel diffing, pinned by
`test_known_limit_a_shifted_horizontal_rule_is_nearly_invisible`).

## Out of Scope

- Fixing the contradictory repair-count claims (Phase 2) or the duplicated contact
  affordances (Phase 3). This spec builds the net that would have caught them; the fixes are
  their own changes.
- Firefox and WebKit. Screenshots need Chromium only, and nothing here has been tested on
  the others — stated rather than implied (CON-VER-007).
- The three defects recorded in #34 (redaction's out-of-frame rewrite, `VALUE_RE`
  over-matching, `--merge-method` parsing). Each changes an exit code, a detection rule or a
  CLI contract and belongs in its own change.

## Constraints

- **GitHub Pages cannot set response headers.** FR-012 exists to record this, not to pretend
  otherwise.
- **The runner is Ubuntu 20.04**: curl 7.68 (no `--retry-all-errors`), python3 3.8 (no
  `tomllib`), no `node` on the runner's PATH by default.
- **Seven runners on four vCPUs.** Three Playwright jobs at once put the load at 10, so a
  timing-sensitive assertion belongs in a benchmark, not a merge gate (CON-VER-008).
- `runs-on: ${{ fromJSON(vars.CI_RUNS_ON || '"ubuntu-latest"') }}` on every job, so unsetting
  the repo variable falls back to hosted without a commit.
