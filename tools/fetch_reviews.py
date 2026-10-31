#!/usr/bin/env python3
"""Archive the shop's Google reviews to disk (spec 015).

WHY THIS EXISTS: the site used to fetch reviews from the Places API at build
time and keep nothing. No review text existed anywhere in the repository, so if
Google removed the listing — or the key lapsed — 549 reviews of social proof
vanished with no copy. This writes them down, and the commit is the point.

WHAT IT CANNOT DO: the Places API returns at most FIVE reviews per place,
whatever the total. The count and average come back in full; the text does not.
The rest need the Google Business Profile API and OAuth against the owner's
account. The archive records that gap rather than hiding it, because "we hold 5
of 549" and "there are 5" are different claims (CON-DATA-002).

    GOOGLE_PLACES_API_KEY=... python tools/fetch_reviews.py
    python tools/fetch_reviews.py --dry-run     # fetch and report; writes nothing

The real fetch runs in CI, where the key already lives.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = REPO_ROOT / "data" / "reviews.json"

PLACES_MAX_REVIEWS = 5
RETRIEVAL_LIMIT = (
    f"The Google Places API returns at most {PLACES_MAX_REVIEWS} reviews per place, "
    "regardless of how many exist. The rating and total count are complete; the "
    "review TEXT is capped. Retrieving the remainder needs the Google Business "
    "Profile API, which requires OAuth against the owner's account."
)


def _review_id(r):
    """Stable identity for a review.

    Places gives no id, so author_url + timestamp is the best available key:
    the same person can leave only one review per place, and the timestamp
    pins the edit.
    """
    return f"{r.get('author_url') or r.get('author_name')}|{r.get('time')}"


# Optional[dict], not `dict | None`: the dev box runs Python 3.8, where the
# union syntax is a TypeError at import. CI is 3.13 and would accept either,
# so this would have passed CI and failed every local run (CON-VER-004).
def build_archive(payload: dict, existing: Optional[dict]) -> dict:
    """Merge a Places response into the existing archive.

    UNION, never replace (FR-007). A response holding fewer reviews than are
    already archived must leave the archive larger than it found it — otherwise
    one bad API call silently destroys the evidence this file exists to keep.
    """
    status = payload.get("status")
    if status != "OK":
        raise ValueError(f"refusing to write: Places returned status={status!r}")

    result = payload.get("result") or {}
    rating = result.get("rating")
    total = result.get("user_ratings_total")
    if not rating or total is None:
        raise ValueError(
            "refusing to write: response carries no rating/user_ratings_total. "
            "Overwriting a good archive with an empty one is worse than failing."
        )

    merged = {}
    for r in (existing or {}).get("reviews", []):
        merged[_review_id(r)] = r
    for r in result.get("reviews", []):
        key = _review_id(r)
        prev = merged.get(key)
        # Keep the longer text: Google sometimes returns a truncated form, and
        # the archive should only ever gain detail.
        if prev and len(prev.get("text") or "") >= len(r.get("text") or ""):
            continue
        merged[key] = r

    reviews = sorted(merged.values(), key=lambda r: r.get("time") or 0, reverse=True)

    return {
        "_why": (
            "Archived Google reviews. Committed so the shop's social proof "
            "survives the listing being removed or the API key lapsing. "
            "Regenerate with tools/fetch_reviews.py; it never deletes."
        ),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "google-places-details",
        "rating": rating,
        "user_ratings_total": total,
        "reviews_retrieved": len(reviews),
        "retrieval_limit": RETRIEVAL_LIMIT,
        "reviews_url": result.get("url"),
        "reviews": reviews,
    }


def write_archive(path: Path, archive: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(archive, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def fetch(place_id: str, key: str) -> dict:
    url = ("https://maps.googleapis.com/maps/api/place/details/json?"
           + urllib.parse.urlencode({
               "place_id": place_id,
               "fields": "rating,user_ratings_total,reviews,url",
               "reviews_sort": "newest",
               "key": key,
           }))
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read())


def _place_id() -> str:
    import re
    cfg = (REPO_ROOT / "hugo.yaml").read_text(encoding="utf-8")
    m = re.search(r'googlePlaceId:\s*"([^"]+)"', cfg)
    if not m:
        sys.exit("googlePlaceId is not set in hugo.yaml")
    return m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and report; write nothing")
    ap.add_argument("--out", default=str(ARCHIVE))
    args = ap.parse_args()

    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        sys.exit("GOOGLE_PLACES_API_KEY is not set. The real fetch runs in CI, "
                 "where the key already lives; it is not brought onto a laptop.")

    out = Path(args.out)
    existing = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None

    archive = build_archive(fetch(_place_id(), key), existing)

    held_before = len((existing or {}).get("reviews", []))
    print(f"rating {archive['rating']} from {archive['user_ratings_total']} reviews")
    print(f"archive holds {archive['reviews_retrieved']} review texts "
          f"(was {held_before})")
    if archive["reviews_retrieved"] < archive["user_ratings_total"]:
        missing = archive["user_ratings_total"] - archive["reviews_retrieved"]
        print(f"  {missing} review texts are NOT retrievable via Places; see "
              f"retrieval_limit in the archive")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    write_archive(out, archive)
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
