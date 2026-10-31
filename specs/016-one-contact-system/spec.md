---
description: "One way to reach the shop per region, per page — and a test that counts them"
status: in-progress
---

# Feature Specification: One Contact System

**Branch**: `feat/one-contact-system` | **Date**: 2026-10-31 | **Constitution**: v2.0.0

## Problem

Counted on the built site, not estimated:

| Page | `tel:` | WhatsApp | `mailto:` | → `/contact` | total |
|---|---:|---:|---:|---:|---:|
| Homepage | 2 | 4 | 2 | 4 | **12** |
| **Contact page** | 4 | 5 | 4 | 2 | **15** |
| `/services/we-repair/` | 2 | 5 | 2 | 4 | **13** |
| Gallery | 2 | 3 | 2 | 3 | **10** |

Fifteen ways to make contact **on the contact page**, including a footer button
whose text is "Go to contact page".

### Where the duplication comes from

The topbar renders **two independent columns** from two unrelated config keys:

- `params.topbar.text` — a strapline carrying the number as **plain unclickable
  text** at ≥992px (`hidden-sm hidden-xs`), and a separate trio of tel/WhatsApp/
  email icons below 992px (`hidden-md hidden-lg`)
- `menu.topbar` — a Phone icon and an Email icon, at **every** width

So at ≥992px the number appears twice, once unclickable. Below 768px two icon
sets stack. PR #12 "fixed" this with 7 lines of CSS capped at 767px — the one
breakpoint nobody complained about — **and shipped with no test**, which is why
it is still here.

## Requirements

- **FR-001** — One contact region in the topbar. `menu.topbar` is deleted; the
  strapline is the single source, and its number is a `tel:` link at **every**
  width, not plain text on desktop.
- **FR-002** — The footer's "Go to contact page" button does not render **on the
  contact page**.
- **FR-003** — ~~Service pages state their call to action once; the bottom CTA
  that is byte-identical to the hero CTA goes.~~ **WITHDRAWN after reading the
  code.** The working plan described these as byte-identical. They are not: the
  bottom one is a terminal CTA *band* with its own heading and lead
  ("Got a device acting up?"), in a different region from the hero, which is
  standard on a long page and is the shop's closing ask. The buttons inside the
  two bands match, which is consistency rather than duplication.

  Removing it would cost a repair shop conversions to satisfy a requirement
  written from an imprecise note — the over-correction this spec's own plan
  warns about. Recorded as withdrawn rather than quietly dropped
  (CON-DATA-003).
- **FR-004** — `contact_url` is `/contact/` with the trailing slash, so the link
  does not take a redirect on every page of the site.
- **FR-005** — Contact addresses come from `hugo.yaml` (Principle X). The second
  address hard-coded into the contact template today traces to nothing.
- **FR-006** — No `target="_blank"` on `tel:` or `mailto:` — it spawns a blank
  tab beside the dialer. *(Already true; asserted so it stays true.)*
- **FR-007** — **A test that counts affordances per region per page.** This is
  the requirement PR #12 lacked; without it the next refactor re-introduces the
  duplication silently.

## Success Criteria

| # | Criterion | Coverage |
|---|---|---|
| SC-001 | No page renders more than one contact affordance per region | ✅ `test_no_region_offers_the_same_route_twice` (seen red on the topbar) |
| SC-002 | The topbar number is a `tel:` link at 1440px and at 390px | ✅ strapline renders one `tel:` link at every width; counted on the built site |
| SC-003 | The contact page does not link to itself from the footer | ✅ `test_the_contact_page_does_not_link_to_itself_from_the_footer` |
| SC-004 | ~~A service page states its CTA once~~ | **withdrawn** — FR-003 above |
| SC-005 | Every internal `/contact` link carries the trailing slash | ✅ `test_internal_contact_links_carry_the_trailing_slash` |
| SC-006 | No `tel:` or `mailto:` has `target="_blank"` | ✅ `test_no_tel_or_mailto_opens_a_new_tab` |
| SC-007 | Contact addresses render from `hugo.yaml` | ✅ contact template renders `params.contactEmails` |

All were OWED when written; the spec preceded the work (CON-PROC-001). Each guard was seen
failing on the real duplication before anything was changed.

Measured on the built site, before and after:

| Page | before | after |
|---|---|---|
| Homepage | tel 2, WhatsApp 4, email 2 | **tel 1, WhatsApp 3, email 1** |
| Contact | tel 4, WhatsApp 5, email 4 | **tel 3, WhatsApp 4, email 3** |
| We Repair | tel 2, WhatsApp 5, email 2 | **tel 1, WhatsApp 4, email 1** |
| Gallery | tel 2, WhatsApp 3, email 2 | **tel 1, WhatsApp 2, email 1** |

What remains is deliberate: the footer block, the fixed WhatsApp/Call buttons, the hero CTA
and the contact form each serve a distinct region.

## Out of Scope

- The floating WhatsApp/Call buttons. They are *one* affordance in *one* region
  (fixed overlay), they are the primary conversion path for a repair shop, and
  removing them is a business decision rather than a duplication fix.
- Visual restyling of what remains — that is spec 017 (design system).

## Constraints

- The topbar is rendered by the **vendored theme**, which is used unforked. The
  change is made through config and `layouts/` overrides, never by editing
  `themes/`.
- Deleting a contact route risks losing enquiries, so the second email address is
  **moved into config**, not deleted — making it traceable without removing a way
  for a customer to reach the shop.
