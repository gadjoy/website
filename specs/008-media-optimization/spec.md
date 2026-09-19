---
description: "Slim the deploy artifact from 1.49 GB to 82 MB without losing any referenced media"
status: shipped
shipped: 2026-06-06
prs: [8]
backfilled: 2026-08-05
---

# Feature Specification: Media Optimization & Build Slimming

**Shipped**: 2026-06-06 via PR #8 | **Backfilled**: 2026-08-05 | **Constitution**: v2.0.0

> **Retrospective spec**, reconstructed from PR #8, commit `a0773c20` (14,834 files changed),
> and `migration/scripts/optimize_media.py`.
>
> Backfilled despite being labelled a `chore/` branch, because it modified the migration
> pipeline and deleted 7,883 files — which Constitution v2.0.0 puts squarely inside
> "touches migration/test infrastructure", i.e. spec required.

## Problem

The migration faithfully imported the entire WordPress uploads directory: ~10,630 files, 1.49 GB.
Most of it was never referenced by any post — WordPress keeps every resized derivative of every
image, plus plugin caches (`wpforms/cache/*.json`, `wp-file-manager-pro/fm_backup/`), plus
originals at camera resolution. Every Pages build uploaded all of it, taking ~4.5 minutes, and
every clone paid for it.

The risk in fixing this is obvious and severe: **delete or convert the wrong file and a post
loses its images, permanently and silently**, across 1,508 posts that nobody is going to review
by hand.

## User Scenarios

### US1 — A visitor loads pages faster (P1)
Images are served as WebP at sane dimensions rather than as multi-megabyte originals.

### US2 — A maintainer's build and clone are fast (P1)
The deploy artifact is small enough that CI spends its time building, not uploading.

### US3 — A maintainer can undo any of it (P1)
Every original remains recoverable, and the whole transformation can be re-run from scratch.

## Requirements

- **FR-001** Only upload files that **no** content file references may be pruned. Reference
  detection MUST be URL-decode aware — migrated filenames contain en dashes and other
  percent-encoded characters, so naïve string matching would report a referenced file as
  unreferenced and delete it.
- **FR-002** Images MUST be converted to WebP, and every reference to a converted file MUST be
  rewritten in the same operation. A converted asset with a stale reference is a broken image.
- **FR-003** Downscaling MUST apply only to images wider than 1400px. Smaller images MUST NOT
  be upscaled or resampled.
- **FR-004** Videos MUST be re-encoded to H.264 with `faststart` so they begin playing before
  fully downloading.
- **FR-005** The entire operation MUST be reproducible from one script
  (`migration/scripts/optimize_media.py`), runnable after any re-migration — it is a pipeline
  stage, not a one-off manual cleanup.
- **FR-006** Originals MUST remain recoverable from `wordpress/backup/` and
  `migration/wp-export/`, and this MUST be documented.
- **FR-007** After optimization, **zero** media references may be broken. This is an invariant,
  not a spot check (Constitution V).
- **FR-008** Reference resolution MUST be **case-exact**. A reference differing from the file
  only by case works on macOS and 404s on the Linux Pages server.

## Success Criteria

| ID | Criterion | Test coverage |
|---|---|---|
| SC-001 | Artifact ≤ 100 MB (from 1.49 GB) | **OWED** — no size assertion exists |
| SC-002 | Zero broken media references in content source | ✅ `test_all_media_resolve_on_disk` |
| SC-003 | Zero broken media references in built output | ✅ `test_internal_refs_resolve` |
| SC-004 | Reference checks are case-exact on every platform | ✅ `conftest.media_ref_resolves` (added PR #14) |
| SC-005 | Every post that had images still has them | ✅ `test_card_banner_present_and_resolves` |
| SC-006 | `optimize_media.py` is idempotent — a second run changes nothing | **OWED** |
| SC-007 | Pruning drops only genuinely dangling references | ✅ `test_prune_missing_media_drops_only_dangling_refs` |

## Out of Scope

- A CDN or image-resizing service. Static assets on Pages are adequate at 82 MB.
- Responsive `srcset` generation — deliberately stripped during migration (`srcset` is a
  forbidden substring in `conftest.FORBIDDEN_SUBSTRINGS`) to keep one canonical path per asset.
- Git history rewriting to reclaim the 1.49 GB from past commits.

## As Built

Delivered the stated numbers: **1.49 GB → 82 MB (~94%)** — 7,883 unreferenced files pruned,
2,715 images converted to WebP, 32 videos re-encoded, logo resized. PR #8's test plan explicitly
records *"0 broken image refs (URL-decode aware)"*, so FR-001 was understood and handled at the
time.

### Deviation: FR-008 was not met, and it cost two live 404s

The optimization ran on macOS, where `Path.exists()` is case-insensitive, and the verification
used exactly that call. So a post referencing `redmi-4-before-dead-condition.webp` when the file
is `Redmi-4-Before-Dead-Condition.webp` verified as fine, and shipped. Both images returned
**404 in production** from this PR (2026-06-06) until PR #14 (2026-08-05) — about two months.

The suite was red for that entire period and nobody saw it, because CI ran no tests and the
last local run had been on the case-insensitive filesystem that cannot detect the fault.

This single defect is the origin of three things now in place: `conftest.media_ref_resolves`
(case-exact by construction), Constitution VIII's corollary that *a test which only passes on
one operating system is a bug in the test*, and the CI gate itself.

### Vendored WordPress themes removed (2026-09-19)

`migration/wp-export/wp-content/themes/` held WordPress's stock themes (`twentytwenty`,
`twentynineteen`, …) — 1,617 tracked files carrying **every Dependabot alert on this repo: 70
open, 14 of them critical**, all from the themes' npm lockfiles. A Hugo site never builds or
serves them, and nothing outside that directory referenced them. Removed and gitignored.

They were never covered by FR-006 (which protects *media* recovery): the shop's uploads live in
`wp-content/uploads/`, untouched, and the reference deck used as a test fixture is in that tree.

**Still outstanding, and deliberately not acted on here:** `migration/wp-export` still holds
**164 MB across 15,554 tracked files**, and `.git` is **3.1 GB**. FR-006 names `wp-export` as a
recovery source for original media alongside `wordpress/backup/`, so emptying it is a real
decision about whether the `.wpress` backup alone is sufficient — not a cleanup. Logged as
`008` D001 rather than done quietly.

## Tests Owed

- **SC-001** — assert the built output stays under a size ceiling. Cheap, and the only guard
  against silently regrowing the artifact; without it the 94% win can erode unnoticed.
- **D001** — decide whether `migration/wp-export` can be reduced to just the test fixture.
  164 MB / 15,554 tracked files, and the repo's `.git` is 3.1 GB. Requires confirming the
  `.wpress` backup alone satisfies FR-006.
- **SC-006** — idempotence. Currently unknown; re-running the script after a re-migration is a
  documented step, so "run twice, expect no diff" is a real risk worth pinning.
