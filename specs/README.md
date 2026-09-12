# Specs Index

Every spec in this repo, and every merged PR's spec status. Maintained so that "did this ship
with any thought written down?" is answerable by reading one file. `test_spec_hygiene.py`
enforces that each `specs/NNN-*/` directory below is real, complete, and listed here.

## Specs

| # | Feature | Status | Shipped | PRs | Artifacts |
|---|---|---|---|---|---|
| [001](001-wp-hugo-migration/) | Faithful WordPress → Hugo migration | shipped | 2026-06-06 | #2 | spec, plan, tasks |
| [002](002-ci-test-gates/) | CI-enforced test gates | shipped | 2026-08-05 | #14 | spec, plan, tasks |
| [003](003-visual-identity/) | Monochrome visual identity & homepage | shipped | 2026-06-06 | #2, #3, #4 | spec *(backfilled)* |
| [004](004-live-google-reviews/) | Live Google reviews + verifiable fallback | shipped | 2026-06-06 | #2 | spec *(backfilled)* |
| [005](005-interactive-service-pages/) | Interactive service pages | shipped | 2026-06-06 | #5 | spec *(backfilled)* |
| [006](006-gallery-lightbox/) | Before/after gallery wall | shipped | 2026-06-06 | #5 | spec *(backfilled)* |
| [007](007-contact-and-enquiry-delivery/) | Contact page & enquiry delivery | shipped | 2026-06-07 | #5, #6, #7, #10, #11 | spec *(backfilled)* |
| [008](008-media-optimization/) | Media optimization & build slimming | shipped | 2026-06-06 | #8 | spec *(backfilled)* |
| [009](009-deck-to-posts/) | Weekly repair deck → published posts | in-progress | — | #18 | spec, plan, tasks |
| [010](010-compensating-controls/) | Compensating controls for an unprotected `main` | shipped | 2026-09-12 | #22 | spec, plan, tasks |

### Why backfilled specs carry `spec.md` but not `plan.md` / `tasks.md`

A plan describes an approach not yet taken and a task list tracks work not yet done. Writing
either after the fact produces a document that was never used to make a decision, and a
checklist ticked in the same commit that created it — which is the exact failure this repo
already has one instance of (`001`'s list sat at 0 of 31 for two months). So a retrospective
spec carries the parts that stay true and stay useful:

- **Requirements** — still binding on the code today, and the source material for the tests it
  is owed.
- **Success criteria with a coverage column** — what is guarded, what is not.
- **As Built** — what actually shipped, and every place the result diverged from the intent,
  recorded rather than tidied away.

Forward specs (`002` onward, and everything new) carry the full `spec → plan → tasks` set.

## Merged PRs with no spec — and whether that was correct

Per Constitution v2.0.0, a spec is required for changes that add or reshape a user-facing
capability, or that touch migration/test infrastructure; and is *not* required for copy edits,
CSS tweaks, dependency bumps, or single-file bug fixes.

| PR | Title | Verdict |
|---|---|---|
| #1 | Re-migrate WordPress blog to Hugo | closed, superseded by #2 — covered by `001` |
| #6 | Fix contact layout lookup on production Hugo | correctly exempt — single-file bug fix. Now recorded in `007` as an incident |
| #7 | Bump CI Hugo to 0.147.2 | correctly exempt — version bump. Root cause now specified in `002` |
| #9 | CI: bump Pages actions to Node 24 majors | correctly exempt — dependency bump |
| #12 | UI: white ring on Call FAB; de-dup mobile topbar icons | correctly exempt — CSS-only. Recorded in `003` SC-005 as an untested class |
| #13 | Fix repair-count claim | **borderline.** Two-file fix, so exempt by the letter; but it changed a public factual claim, which is Principle X territory. Treated as exempt, guarded by a test in #14 |

Everything else that shipped without a spec is now backfilled above. **Nothing merged remains
unaccounted for.**

## Tests Owed

Consolidated from the coverage tables in each spec. This is the real coverage backlog — the
honest statement of what is specified but not guarded.

### Cheap and worth doing next
| Owed | Spec | Note |
|---|---|---|
| Table-driven layout check for services + gallery | `005` SC-002, `006` SC-002 | Generalise `test_contact_page_uses_project_layout` over (URL, marker) pairs. Both resolve layouts by a *different* Hugo lookup path than contact, and neither is guarded against the #6/#7 class |
| Built-output size ceiling | `008` SC-001 | The only guard against silently regrowing the 82 MB artifact |
| No API key in repo or built output | `004` SC-003 | Grep-style assertion |
| No fabricated testimonials in `data/` | `004` SC-004 | Trivial |
| Lazy-loading + WebP on gallery images | `006` SC-005 | Output assertion |
| Recent-repairs scroller shows 15, newest first | `003` SC-003 | Output assertion |
| Scan images embedded in tracked Office/PDF files | `009` D003 | The PII gate covers `static/img/uploads` only. The reference deck sits in the public repo and one embedded image shows a 'Serial number' label; no value was extractable, so low severity, but the blind spot is real |

### Needs a browser harness (deferred — `002` D001)
| Owed | Spec |
|---|---|
| Hero renders, no owl carousel | `003` SC-001 |
| Floating buttons legible on dark sections | `003` SC-005 — *this is the #12 bug* |
| `prefers-reduced-motion` disables animation | `003` SC-006, `005` SC-004 |
| Tiles / timeline / reason cards present | `005` SC-003 |
| Lightbox opens and closes by keyboard | `006` SC-004 |
| Info cards and map render | `007` SC-008 |

### Deliberately manual — do not automate
| Item | Spec | Why |
|---|---|---|
| End-to-end enquiry submission | `007` SC-009 | Automating it delivers junk to a real customer inbox. Verify by hand after any form change |
| Live-key review build | `004` SC-001 | Needs a credential; one manual check per key rotation |

### Unknown
| Item | Spec | Why |
|---|---|---|
| `optimize_media.py` idempotence | `008` SC-006 | Documented as re-runnable after a re-migration, never verified. "Run twice, expect no diff" |

### Closed
| Item | Spec | Outcome |
|---|---|---|
| No IMEI/serial/MAC visible in published photos | `006` FR-007 / SC-006 | **Closed 2026-08-06.** Was listed above as *"not checkable by parsing HTML — content-review task, not a test"*. That was wrong twice over. It *is* checkable by OCR, made cheap by keying a reviewed-images manifest on **content hash** so the build only OCRs new or changed files. And the scale was far larger than the two images originally reported: an OCR sweep of all 2,711 uploads flagged 241, of which **229 were real device screens** — serials, IMEI pairs and two MAC addresses, spanning 2021-12 to 2025-01. All 229 redacted (photos kept); enforced by `test_no_device_identifiers.py`. Two lessons generalise: "needs a human" deserves a second look before it becomes permanent, and a reported instance count is a lower bound, not a scope. |

## Conventions

- Directories are `NNN-kebab-slug`, numbered sequentially, never renumbered once referenced.
- Frontmatter carries `status`, `shipped`/`prs` where applicable, and `backfilled` for
  retrospectives — so this index and the hygiene test can be checked mechanically.
- A spec's coverage table is updated when a test lands, and the Tests Owed register above is
  updated with it.
