---
description: "One page-hero partial, one card surface, one heading underline — and styling for the two pages I shipped bare"
status: in-progress
---

# Feature Specification: Hero & Card Components

**Branch**: `feat/hero-and-card-components` | **Date**: 2026-11-07 | **Constitution**: v2.0.0

## Problem

Deferred from spec 017 until the design tokens existed; they now do. Measured in
the repository, not taken from the old plan:

- **The page hero is hand-copied three times** — `contact.html`,
  `services-list.html`, `services/single.html` — same section, eyebrow, title,
  sub-line and button row, drifting independently. (The homepage hero is a
  different two-column design and is not part of this.)
- **The card surface is declared four times.** `.svc-card`, `.gadjoy-review`,
  `.box-image-text` and the new `.gj-card` each repeat white background, hairline
  border and medium shadow.
- **Section headings draw two underlines at once.** The theme gives
  `.heading h2` a full-width 5px `border-bottom`; `custom.css` adds a centred
  56px bar via `:after`. Both render.
- **Two pages I shipped render bare cards.** `/services/` uses `gj-card
  gj-service-card` and `/testimonials/` uses `gj-review-card`. **None of those
  three classes has any CSS.** Specs 015 and 017 shipped them unstyled, and
  nothing caught it because no test asks whether a class in the markup exists in
  the stylesheet.

## Requirements

- **FR-001** — One `partials/page-hero.html`, taking eyebrow, icon, title,
  sub-line and buttons. The three copies call it. **Value-preserving**: the
  pages it serves must render pixel-identically.
- **FR-002** — The card surface is declared **once**, in a shared rule. Each card
  keeps only what genuinely differs (padding, layout, a larger radius).
  **Value-preserving** for every existing card.
- **FR-003** — `.gj-card`, `.gj-service-card` and `.gj-review-card` get real
  styling. This *is* a visual change, and intended.
- **FR-004** — Section headings draw **one** underline: the short centred bar.
  The full-width border goes. Intended visual change.
- **FR-005** — Every `gj-`/`gadjoy-` class used in a template has at least one
  rule in `custom.css`. The test that would have caught FR-003's defect.

## Success Criteria

| # | Criterion | Coverage |
|---|---|---|
| SC-001 | Hero markup appears in exactly one template | OWED |
| SC-002 | The three hero pages are pixel-identical after the change | OWED |
| SC-003 | The card surface trio is declared in one rule | OWED |
| SC-004 | Existing card pages are pixel-identical after the change | OWED |
| SC-005 | No project class is used in markup without a CSS rule | OWED |
| SC-006 | Section headings carry no full-width border | OWED |

All OWED: the spec precedes the work (CON-PROC-001).

## Out of Scope

- The homepage two-column hero — a different component, not a copy.
- Letter-spacing and casing of headings. The old plan called them "opposite to
  every other heading"; that is a taste call, not a defect, and is left to the
  owner.
