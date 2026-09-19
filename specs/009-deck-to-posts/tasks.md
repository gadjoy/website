---
description: "Task list for deck-to-posts publishing"
---

# Tasks: Weekly Repair Deck → Published Posts

> **Status: Phases A–C COMPLETE; publisher + workflow written but NOT yet rehearsed.**
> T021/T022/T025 need the private intake repo and its token — owner actions, so they are
> **Status: A–D COMPLETE and rehearsed end to end.** Only T022 (mint a PAT) and T026 (watch one
> real batch, then enable auto-merge) remain, both owner actions. Verified: `pytest` **138
> passed** (was 98); deck mutations 4/4 caught; live rehearsal against gadjoy/repairs-intake
> issue #1 produced 4 posts, 5 reasoned skips, one redaction, and closed the issue.

**Input**: `specs/009-deck-to-posts/{spec,plan}.md` | **Constitution**: v2.0.0

---

## Phase A: Unblock growth (blocking prerequisite)

- [x] T001 Confirm RED: add a throwaway post and watch `test_post_count_matches_source` and
      `test_url_preservation_via_aliases` fail. Proves the blocker is real before touching it.
- [x] T002 Add an `is_migrated()` helper to `conftest.py` — a post is migrated iff it has no
      `origin` key.
- [x] T003 Re-scope `test_post_count_matches_source`: migrated `== 1508` **and** total `>= 1508`.
- [x] T004 Re-scope `test_url_preservation_via_aliases` to migrated posts only (FR-018).
- [x] T005 Prove the loosened gate still bites: a test asserting the migrated-count check fails if
      a migrated post disappears, and that an `origin: deck` post is not exempt from the other
      invariants (taxonomy, banner, artifacts).

## Phase B: Parser (US1, US4)

- [x] T006 [P] Golden fixture test: reference deck → exactly 4 repairs, 5 skips with reasons
      (SC-001). Confirm RED.
- [x] T007 [P] Test before/after by x-position, asserting **slide 7** specifically, where filename
      order is inverted (SC-002).
- [x] T008 [P] Test title = topmost shape; both captions verbatim; footer furniture stripped
      (SC-003).
- [x] T009 [P] Test a repair-shaped slide with no usable title raises (SC-004).
- [x] T010 [P] Test the video-bearing slide (9) does not crash (SC-005).
- [x] T011 Implement `parse_deck()` in `tools/deck_to_posts.py` until B is GREEN.

## Phase C: Generation + privacy interlock (US2, US3)

- [x] T012 [P] Test slug derivation + dedupe against all 1,508 existing slugs (SC-010).
- [x] T013 [P] Test categories emit only existing slugs; unmapped → `[repair]` (FR-013).
- [x] T014 [P] Test post date comes from the issue, never the slide (FR-009).
- [x] T015 [P] Test idempotence: same deck twice → no second post (SC-007).
- [x] T016 [P] Test the PII interlock redacts an About-screen image before it is written (SC-008).
- [x] T017 Implement `build_post()` + writer until C is GREEN.
- [x] T018 **Mutation-test the interlock**: disable it and confirm the test fails. A guard never
      seen to fail is a guess.
- [x] T019 Integration: generated posts pass the full existing suite + `hugo --minify` + the
      build-output tests (SC-006).
- [x] T020 Wire manifest regeneration into the publish workflow, with a re-scan of the written
      images that fails the run rather than opening a PR if any identifier survived. (Not
      exercised against real output yet — the dry run writes nothing, so this is verified by
      inspection until T025.)

## Phase D: Publisher + workflow

- [x] T021 Created **gadjoy/repairs-intake** (private) with the `deck.yml` Issue Form, a README
      stating the About-screen rule, and `decks/` for decks over the 25MB attachment cap.
- [ ] T022 **BLOCKED (owner action).** Create the `INTAKE_TOKEN` fine-grained PAT, read-only on
      the intake repo's issues + contents. GitHub has no API for minting a PAT — by design, a
      credential can only be created by a human in the UI. Needed *only* for the unattended
      Actions run; the local path (`INTAKE_TOKEN=$(gh auth token)`) needs no new credential and
      is what the rehearsal used.
- [x] T023 `tools/publish_decks.py` — issue discovery, deck download, PR creation, issue
      comment/close.
- [x] T024 `.github/workflows/publish-decks.yml` — `workflow_dispatch`, branch `content/deck-<week>`
      (**not** `feat/`, or the spec gate blocks it).
- [x] T025 Rehearsed for real against the live private repo (issue #1): deck fetched over the
      contents API (6.4MB, raw media type), 4 posts generated, 5 slides skipped with reasons, a
      serial redacted, duplicate-title warning fired, issue commented and closed. Generated
      posts were deliberately NOT committed — the 2022 reference deck's repairs were published
      on WordPress years ago, so they would duplicate existing content.

## Phase E: Hand over

- [ ] T026 Watch one real batch through by hand, then enable auto-merge.
- [ ] T027 Update `specs/README.md` coverage + Tests Owed register as SC rows turn ✅.

---

## Deferred / decided against

- [ ] D001 Back-fill the 2025-02 → 2026-08 gap from older decks — one run once the pipeline is
      trusted, not part of building it.
- [ ] D002 `/tv/` page. The deck already drives the store TV; the site does not need to.
- [x] D004 **RESOLVED — and it was worse than recorded.** The video was not merely unpublished:
      `<a:videoFile>` is DrawingML and the parser looked in presentationml, so `Repair.video`
      was **always None**. The test asserted only `hasattr(r, "video")`, which passes for a
      permanently-null attribute — the fourth vacuous guard found in this repo. Namespace fixed,
      detection now asserted on real bytes, and a slide's video is **reported as held back**
      rather than dropped silently (FR-010). Videos stay unpublished on purpose: the privacy
      interlock OCRs stills and cannot read video frames, so embedding a clip would let an
      About screen bypass the redaction that 229 images were cleaned for. Embedding is deferred
      to D006 below.
- [ ] D006 Publish deck videos, once the privacy scan can sample video frames. Until then a
      clip is held back and the team is told why.
- [ ] D004-OLD (superseded) **A deck's video is parsed but never published.** `parse_deck` extracts the
      `videoFile` from slide 9 and `Repair.video` carries it, but `build_post` ignores it, so a
      repair filmed on video loses the video with no note in the report. FR-010 said "embed it
      or skip it with a recorded reason" — it is currently skipped *silently*, and the test only
      asserts the run does not crash. Either embed a `<video>` (Hugo already allows raw HTML and
      the migrated posts contain video blocks) or report the skip.
- [x] D005 **CLOSED — not a blocker; the original claim was wrong.** Tested rather than assumed:
      both publish paths (`publish-decks.yml` and `make publish`) run
      `build_reviewed_manifest.py` before the tests run, so new images are already in the
      manifest and the unreviewed count is zero. The ceiling only bites if images are added by
      hand without regenerating, which is the case it was written for. Verified by publishing
      the reference deck locally and running the PII gate: 3 passed.
- [ ] D003 **PII gate blind spot found during the rehearsal.** `test_no_device_identifiers`
      scans `static/img/uploads` only, so photos embedded inside tracked Office/PDF files are
      invisible to it. The reference deck is committed in the *public* repo and one of its
      embedded images (`image9.jpg`) shows a 'Serial number' label — OCR could not read the
      value, so severity is low, but the gap is real. Two such files are tracked.
