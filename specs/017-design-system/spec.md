---
description: "Design tokens, two dead pages fixed, one WhatsApp number, and the social cards the site never had"
status: in-progress
---

# Feature Specification: Design System & Two Dead Pages

**Branch**: `feat/design-system` | **Date**: 2026-10-31 | **Constitution**: v2.0.0

## Problem

There is no system to be inconsistent with, which is what reads as a personal
project rather than a business. Counted in `static/css/custom.css`:

| | count |
|---|---:|
| distinct `box-shadow` values | 16 |
| distinct `border-radius` values | 7 |
| hard-coded `#000`/`#000000` | 38 |
| files hard-coding the WhatsApp number | 4 |

**Two pages are broken**, and both were verified on the live site rather than
taken from a note:

- **`content/_index.md` has body copy that has never been seen.** It opens
  "## Bangalore's bench for when tech breaks." and no homepage layout renders
  `.Content`, so it has never appeared.
- **`/services/` renders as an empty blog listing.** It returns 200 with
  `class="blog-entries"` and no entries, because the two service pages are not
  blog posts. A customer following the nav lands on a blank page.

The site also emits **no Open Graph tags**, so every link shared on WhatsApp —
the shop's primary channel — renders as a bare URL.

## Requirements

- **FR-001** — Shadows, radii, and the brand greys become **tokens** on `:root`.
  Existing values collapse onto the token set; a new literal is a deliberate act.
- **FR-002** — The WhatsApp number is declared **once** in `hugo.yaml` and read
  everywhere, so a number change is one edit rather than four.
- **FR-003** — `/services/` lists the actual services, not an empty blog roll.
- **FR-004** — `content/_index.md`'s body either renders or the file stops
  pretending to hold copy. **Rendering it is preferred** — it is written, it is
  good, and it has been invisible for months.
- **FR-005** — Open Graph and Twitter card tags on every page, with the image
  traced to config.
- **FR-006** — Page titles carry the business name, so a browser tab and a
  search result identify the shop.

## Success Criteria

| # | Criterion | Coverage |
|---|---|---|
| SC-001 | No `box-shadow` or `border-radius` literal outside the token block | ✅ `test_shadows_and_radii_come_from_tokens` — 16 shadows, 0 literals left |
| SC-002 | The WhatsApp number appears once in the repository | ✅ `test_the_whatsapp_number_is_declared_once` |
| SC-003 | `/services/` links to both service pages | ✅ `test_services_lists_the_services` |
| SC-004 | `/services/` does not render a blog listing | ✅ `test_services_is_not_an_empty_blog_listing` |
| SC-005 | The homepage renders `_index.md`'s body | ✅ `test_the_homepage_renders_the_index_body` |
| SC-006 | Every page carries `og:title`, `og:description`, `og:image` | ✅ `test_every_page_carries_open_graph_tags` |
| SC-007 | `og:image` resolves to a real file | ✅ `test_the_og_image_resolves_to_a_real_file` — caught a 404'ing config value |
| SC-008 | Page titles contain the business name | ✅ `test_page_titles_carry_the_business_name` |

All were OWED when written; the spec preceded the work (CON-PROC-001). Ten of the eleven
guards were red against the live site before anything changed.

**SC-007 found a defect nobody had reported.** `default_sharing_image` pointed at
`img/sharing-default.png`, which **did not exist** and 404'd on the live site — so every
link shared on WhatsApp rendered a *broken* card, which is worse than a plain one. The
asset is now generated from the brand mark at 1200×630 by the same script that makes the
icons, so it cannot drift from them.

## Out of Scope

- The hero partial consolidation and `.gj-card` unification from the working
  plan. Both are large refactors of working markup whose only visible outcome is
  "the same, but tidier" — and every one of them would move the visual
  baselines. Deferred deliberately, not forgotten: tokens first, because tokens
  are what make that refactor safe to do later.
- Dropping the unused Roboto font and dead `#blog-listing-big` — trivial, and
  bundled into the token work rather than specified separately.

## Constraints

- The theme is vendored and used unforked; changes go through `layouts/`
  overrides and config.
- Token substitution must be **value-preserving**. A design system that silently
  changes the look is a redesign wearing a refactor's clothes, and the visual
  baselines are what prove it did not.
