# Implementation Plan: Reviews Archive

**Spec**: [spec.md](spec.md) | **Date**: 2026-10-31

## Shape of the archive

`data/reviews.json` holds both the evidence and its own limits:

```
{
  "fetched_at": "...", "source": "google-places-details",
  "place_id": "...",
  "rating": 4.7, "user_ratings_total": 549,
  "reviews_retrieved": 5,
  "retrieval_limit": "The Places API returns at most 5 reviews per place.
                      The remaining 544 need the Business Profile API (OAuth).",
  "reviews": [ ... ]
}
```

`reviews_retrieved` beside `user_ratings_total` is the point: anyone reading the
file can see the archive is partial and why, without digging for it (CON-DATA-002 —
"we hold 5 of 549" is not the same claim as "there are 5").

## Merge, never replace (FR-007)

The fetcher reads the existing archive and **unions** by review id, keeping the
longest text when the same review appears twice. A run that returns fewer reviews
than are already held must leave the file larger than it found it.

Without this the archive is a cache with extra steps: one bad API response and the
evidence is gone — which is the exact failure this spec exists to prevent.

## Publishing

`/testimonials/` lists everything held, **unfiltered**. The current
`where .reviews "rating" ">=" 4` goes. A 4.7 shown with its criticism is more
persuasive than a wall of five-star quotes, and the filter was invisible to a
reader, which makes it the worse kind of omission.

JSON-LD comes from the same file as the visible page, so the two cannot disagree.
Emitting a rating in structured data that the page does not show would be the
machine-readable version of lying.

## The secret stays where it is

`GOOGLE_PLACES_API_KEY` is a repository secret and will not be brought onto this
machine or into this conversation. A `workflow_dispatch` job runs the fetch in CI
and uploads the result for review before it is committed — the pattern the visual
baselines already use, and the same reasoning: the thing that needs credentials
runs where the credentials already are.

## Risks

- **A partial archive read as complete.** Mitigated by FR-006 and by the page
  stating how many of the total it holds.
- **The fetch could return junk and overwrite good data.** Mitigated by the merge
  rule and by validating the payload shape before writing.
