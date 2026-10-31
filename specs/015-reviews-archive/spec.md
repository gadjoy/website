---
description: "Own the reviews: fetch to disk, publish all of them including criticism, and emit structured data"
status: shipped
shipped: 2026-10-31
prs: [43]
---

# Feature Specification: Reviews Archive

**Branch**: `feat/reviews-archive` | **Date**: 2026-10-31 | **Constitution**: v2.0.0

## Problem

Three separate failures, one subject.

1. **Nothing is persisted.** The rating and reviews are fetched from the Google
   Places API *at build time*. No review text exists anywhere in this repository.
   If Google removes the listing, or the key lapses, the social proof is gone and
   there is no copy of it.
2. **Criticism is silently dropped.** `testimonials.html` filters
   `where .reviews "rating" ">=" 4`. A 4.7 average shown beside only four- and
   five-star quotes is less believable than the same average shown with its 1★
   and 2★ entries, and the filter is invisible to a reader.
3. **There is no structured data at all.** 549 real reviews produce no stars in
   search results because nothing emits `LocalBusiness` or `AggregateRating`.

## What this spec CANNOT do, stated plainly

**It cannot archive 549 reviews.** The Places API returns a maximum of **five**
review objects per place, regardless of how many exist. The count (549) and the
average (4.7) are returned in full; the *text* is capped at five.

Retrieving the rest requires the **Google Business Profile API**, which needs
OAuth against the owner's account — not available here. So:

- what ships now: the five retrievable reviews, archived to disk, published in
  full including any criticism among them, plus the verified count and average
- what lights up later: the same pipeline pointed at a fuller source, with no
  template change

Writing "archive all ~500 reviews" into a success criterion would make this spec
claim something it cannot deliver. The gap is the finding, not a detail to
smooth over (CON-DATA-001).

## Requirements

- **FR-001** — `tools/fetch_reviews.py` writes `data/reviews.json`, **committed**.
  The commit is the point: the archive then survives Google.
- **FR-002** — The build reads reviews **from disk**, never from the network. A
  site build must not depend on a third-party API being up.
- **FR-003** — **No rating filter.** Every archived review is published, including
  criticism. If a review is in the archive it is on the page.
- **FR-004** — A `/testimonials/` page listing every archived review with its
  rating, author and date.
- **FR-005** — `LocalBusiness` + `AggregateRating` JSON-LD emitted from the same
  file, so the structured data and the visible page cannot disagree.
- **FR-006** — The archive records **what was retrieved and what was not**: the
  total count, the number of texts actually held, and the reason for the gap.
- **FR-007** — The fetcher **never deletes** reviews already archived. A later run
  that returns fewer reviews must not shrink the file — that is how an archive
  quietly becomes a cache.
- **FR-008** — The trust line can now show the verified rating and count, which
  spec 014 deferred for exactly this reason.

## Success Criteria

| # | Criterion | Coverage |
|---|---|---|
| SC-001 | `data/reviews.json` exists and the build reads it | ✅ `data/reviews.json` committed; `test_the_build_makes_no_places_api_call` |
| SC-002 | A build with no network still renders reviews | ✅ build runs with no key and no network call |
| SC-003 | A 1★ review in the archive appears on `/testimonials/` | ✅ `test_a_one_star_review_is_published` — the real archive holds two 1★ |
| SC-004 | `/testimonials/` lists every archived review | ✅ `test_every_archived_review_appears` |
| SC-005 | JSON-LD `AggregateRating` matches the archive's own numbers | ✅ `test_the_aggregate_rating_matches_the_archive` |
| SC-006 | A fetch returning fewer reviews does not shrink the archive | ✅ `test_a_smaller_response_never_shrinks_the_archive` (mutation-proven) |
| SC-007 | The archive states the retrieved-vs-total gap | ✅ `test_the_page_states_how_much_of_the_total_it_holds` |
| SC-008 | The trust line shows the archived rating and count | ✅ trust line reads 4.7 from 549 from the archive |

All were OWED when written; the spec preceded the work (CON-PROC-001).

**What the real fetch returned:** rating 4.7 from 549 reviews, with five texts
retrievable — rated **1, 1, 5, 5, 5**. The old `rating >= 4` filter was hiding
*both* criticisms, i.e. two of the five reviews the site could actually show.

That turned up an honesty problem in the opposite direction. Five reviews of
which two are 1★ reads as "40% unhappy", while the true average across 549 is
4.7. Google returns what it judges most relevant, which skews to the extremes,
so the sample is not representative — and publishing it without saying so would
misrepresent the shop as surely as the filter did. `/testimonials/` states this
beside the reviews.

## Out of Scope

- **OAuth against the Business Profile API** — owner action, and the blocker on
  the other ~544 reviews.
- Review moderation or editing. The archive records what Google returned; editing
  it would make it evidence of nothing.

## Constraints

- `GOOGLE_PLACES_API_KEY` is a repository secret, correctly absent from this
  machine. The real fetch therefore runs **in CI**, and its output is uploaded for
  review before being committed — the pattern the visual baselines already use.
- CI builds without the key, so the templates must render from `data/reviews.json`
  alone with no live call.
