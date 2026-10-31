# Implementation Plan: One Contact System

**Spec**: [spec.md](spec.md) | **Date**: 2026-10-31

## Order

The counting test lands **first and red**. PR #12's failure was shipping a fix with
no test; repeating that here would be the same mistake with better intentions.

## The counting rule

"One per page" is wrong — a customer at the bottom of a long post should not scroll
back up to find a phone number. The rule is **one per region**, where a region is a
distinct part of the page a visitor encounters separately:

| Region | Allowed |
|---|---|
| topbar | 1 |
| hero / page CTA | 1 |
| in-page form | 1 submit route (plus its named alternative) |
| footer | 1 |
| fixed overlay (FAB) | 1 |

Counting by region rather than by page is what makes the test survive contact with
reality. A flat cap would be gamed within a week by moving a link.

## Phase A — The test PR #12 never had
Parse each built page, bucket every `tel:`/`wa.me`/`mailto:`/`/contact` link by the
region it sits in, assert the per-region cap. Written against the current tree,
expected to fail on the topbar.

## Phase B — The topbar
Delete `menu.topbar`. Rewrite `params.topbar.text` as one strapline whose number is
a `tel:` link at all widths. The theme is unforked, so this is config only.

## Phase C — Footer and service pages
Suppress the footer contact button on the contact page — a button labelled "Go to
contact page" rendered on the contact page is the clearest symptom in the set. Drop
the duplicate bottom CTA on service pages. Fix `contact_url` to carry its slash.

## Phase D — Addresses into config
The second address is hard-coded in the template and traces to nothing. It is
**moved into `hugo.yaml`, not deleted**: removing a contact route could lose a
customer enquiry, and that is not a call to make inside a de-duplication change.

## Risks

- **Over-correction.** Stripping contact routes from a repair shop's site to satisfy
  a counter would be worse than the duplication. The FAB stays, the footer block
  stays; only genuine repeats within one region go.
- **Baselines will move** — the topbar changes on every page. Recapture on the
  runner and review, as before.
