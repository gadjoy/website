---
description: "Serve Sora and Inter from gadjoy.in, and retire Roboto"
status: in-progress
prs: []
---

# Feature Specification: Self-Hosted Fonts

**Branch**: `feat/self-hosted-fonts` | **Date**: 2026-11-13 | **Constitution**: v2.0.0

## Problem

Measured on the built site, 2026-11-13:

- **Sora and Inter come from Google.** `custom.css` opens with an `@import` of
  `fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Inter:wght@400;500;600;700&display=swap`,
  so the stylesheet waits on a third party before it can even discover the font
  files, and every page view tells Google who visited.
- **Whether the fonts had arrived was a race in the screenshot gate.** Spec 017's
  baselines moved on every text row because of it (gadjoy #44), and the capture
  had to learn to wait on `document.fonts.ready` and assert the faces loaded.
- **Roboto is loaded on every page for 46 elements.** The theme's
  `headers.html` links seven Roboto weights. Body text is Inter (407 elements)
  and headings Sora (73); Roboto survives only where the theme's class
  selectors out-rank `custom.css`'s element selectors — `.btn` buttons and the
  `.stat .label` captions. It is a leftover, not a choice.

## Requirements

- **FR-001** — Sora and Inter are served from `/fonts/` with the exact files and
  `unicode-range` subsets Google serves for the request above. **Value-preserving**:
  every page renders pixel-identically to the current baselines.
- **FR-002** — No template or stylesheet the site ships references
  `fonts.googleapis.com` or `fonts.gstatic.com`, and the preconnects to them go.
- **FR-003** — Every `url()` in `fonts.css` resolves to a file in `static/fonts/`,
  and every file there is referenced. A missing file falls back silently to a
  system font, which is exactly the failure spec 017 shipped once.
- **FR-004** — Buttons and stat captions render in Inter; Roboto is no longer
  linked. **Intended visual change**, attributed in its own commit so the
  baseline diff can be read.
- **FR-005** — No visible element on a key page computes to Roboto.
- **FR-006** — The screenshot fingerprint renders the site's own font files,
  not Google's, so it measures what the pages use.

## Success Criteria

| # | Criterion | Coverage |
|---|---|---|
| SC-001 | Shipped templates and CSS carry no Google Fonts host | ✅ `test_no_shipped_file_references_google_fonts` |
| SC-002 | `fonts.css` and `static/fonts/` agree both ways | ✅ `test_every_font_url_resolves_and_every_file_is_used` |
| SC-003 | Both families declared at every weight the site uses | ✅ `test_fonts_css_declares_the_weights_the_site_uses` |
| SC-004 | Every built page links `fonts.css` before `custom.css` | ✅ `test_built_pages_load_the_self_hosted_fonts` |
| SC-005 | Step 1 is pixel-identical | ✅ e2e comparison green on the step-1 commit against unchanged baselines (13/14 compared per run; see tasks T-4) |
| SC-006 | No visible element computes to Roboto | ✅ `test_no_element_renders_in_roboto` — red on 7/7 pages first |
| SC-007 | Step 2's baseline change is buttons and captions only | ✅ every page < 0.21%; buttons and captions only (tasks T-8) |

All OWED when written; the spec precedes the work (CON-PROC-001).

## Out of scope

- Font Awesome and Bootstrap are still loaded from CDNs. Same argument applies;
  separate change, because Font Awesome's icon font is ~300 KB and wants its own
  subsetting decision.
- The heading style (owner's taste call).
