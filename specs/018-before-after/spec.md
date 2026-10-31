---
description: "Phase 6: measure what the five phases actually changed, on the live site"
status: shipped
shipped: 2026-10-31
prs: [45]
backfilled: true
---

# Feature Specification: Before / After

**Date**: 2026-10-31 | **Constitution**: v2.0.0

## Purpose

Close out phases 2–5 by measuring the result against the live site rather than
against the plan. Written after the work, and marked `backfilled` for that
reason rather than back-dated (CON-PROC-005).

## Requirements

- **FR-001** — Every claim of improvement is a measurement taken from
  `https://gadjoy.in`, not from the repository.
- **FR-002** — Things that did not improve, or got worse, are listed beside the
  things that did (CON-REP-002).

## Success Criteria

| # | Criterion | Coverage |
|---|---|---|
| SC-001 | Every figure below is reproducible from the live site | ✅ commands recorded in As Built |
| SC-002 | Deferred and unresolved work is named | ✅ "What is still open" |

## As Built

### Measured on the live site

| | Before | After |
|---|---|---|
| Contradictory repair claims | 15,000+ vs 1,500+ | one figure, from config |
| Star rating | `★★★★★` hard-coded (real 4.7) | ★★★★½ 4.7 from 549, from the archive |
| Unsupported "15+ device brands" | present | deleted |
| Contact affordances, homepage | tel 2 · WhatsApp 4 · email 2 | tel 1 · WhatsApp 3 · email 1 |
| Contact affordances, contact page | 15 | 10 |
| Reviews archived to disk | 0 | 5 texts + 4.7/549, committed |
| Criticism published | filtered out | all of it |
| Structured data | none | `LocalBusiness` + `AggregateRating`, agreeing with the page |
| Open Graph tags | none | full set, image 200 |
| `/services/` | empty blog listing | lists both services |
| `content/_index.md` body | never rendered | on the homepage |
| `og:image` | 404 | 1200×630, generated |
| Unit tests | 185 | 519 |
| Coverage (CI interpreter) | never measured | 95.26% |
| Visual baselines | none | 14, webfont-deterministic |
| Secret scanning | disabled | enabled, repo + fleet-wide |

Reproduce: `./scripts/smoke.sh https://gadjoy.in`, plus the per-item commands in
the PR bodies for specs 014–017.

### What this did NOT fix

- **The other ~544 review texts.** The Places API caps at five. Needs OAuth
  against the Business Profile API — owner action, and the pipeline is built so
  no template changes when it lands.
- **One `page-hero.html`, one `.section-title`, one `.gj-card`.** Deferred in
  spec 017 with a reason: large refactors of working markup whose visible
  outcome is "identical, but tidier".
- **Four recorded defects**, each pinned by a characterisation test rather than
  fixed: the redaction tool's out-of-frame rewrite, `VALUE_RE` over-matching,
  `--merge-method` parsing, `optimize_media`'s uploads-wipe path.
- **The exposed OpenAI key was not rotated.** The owner assessed it as inactive;
  that is a decision, not a verification, and `SECURITY.md` says so.
- **Private-repo secret scanning** needs a paid plan — 28 repos, fleet#43.

### Where I was wrong

Recorded because the diff is the history of why things are the way they are.

- Called gadjoy's lack of self-hosted runners "fleet drift". The repo is public,
  Actions minutes are free, and the fleet rule is scoped to private repos.
- Reported "PRs green" when the fact that mattered was "the site is unchanged" —
  four PRs sat unmerged and the PWA could not be installed.
- Claimed a misplaced CSS `@import` had killed the webfonts. It had not; moving
  it back changed nothing. The real cause was a webfont loading race in the
  capture.
- Shipped roughly a dozen vacuous tests, every one caught by mutation and none
  by reading them.
