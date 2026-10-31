"""Reviews reach the page, unfiltered, and the structured data agrees with it.

Spec 015, FR-002..FR-005.

These build the site with a FIXTURE archive rather than the committed one, so
they assert behaviour (a 1-star review is published; the JSON-LD matches the
page) instead of today's numbers, which change whenever the shop earns another
review.
"""
import json
import os
import re
import subprocess

import pytest

from conftest import REPO_ROOT

FIXTURE = {
    "rating": 4.7,
    "user_ratings_total": 549,
    "reviews_retrieved": 3,
    "retrieval_limit": "Places caps at 5; the rest need the Business Profile API.",
    "reviews_url": "https://maps.google.com/x",
    "reviews": [
        {"time": 300, "rating": 5, "text": "Fixed my dead Redmi in a day.",
         "author_name": "Asha", "relative_time_description": "a week ago"},
        {"time": 200, "rating": 1, "text": "Took three days longer than quoted.",
         "author_name": "Ravi", "relative_time_description": "a month ago"},
        {"time": 100, "rating": 4, "text": "Fair price, honest diagnosis.",
         "author_name": "Meera", "relative_time_description": "two months ago"},
    ],
}


@pytest.fixture(scope="module")
def site_with_reviews(tmp_path_factory):
    """Build the real site with the fixture archive swapped in, then restore."""
    data = REPO_ROOT / "data" / "reviews.json"
    backup = data.read_text(encoding="utf-8") if data.is_file() else None
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps(FIXTURE), encoding="utf-8")

    out = tmp_path_factory.mktemp("reviewsite")
    try:
        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_PLACES_API_KEY"}
        proc = subprocess.run(
            ["hugo", "--minify", "--destination", str(out), "--logLevel", "warn"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=900, env=env)
        assert proc.returncode == 0, proc.stderr[-1500:]
        yield out
    finally:
        if backup is not None:
            data.write_text(backup, encoding="utf-8")
        else:
            data.unlink()


def _read(site, rel):
    return (site / rel).read_text(encoding="utf-8", errors="ignore")


def _ld(html):
    m = re.search(r"<script type=[\"']?application/ld\+json[\"']?>(.*?)</script>", html, re.S)
    assert m, "no JSON-LD on the page"
    return json.loads(m.group(1))


def test_the_build_makes_no_places_api_call():
    """FR-002. A site build must not depend on a third party being up — and CI
    has no key, which is how a hard-coded five-star fallback got there."""
    tmpl = (REPO_ROOT / "layouts" / "partials" / "testimonials.html").read_text()
    assert "resources.GetRemote" not in tmpl
    assert "maps.googleapis.com" not in tmpl


def test_a_one_star_review_is_published(site_with_reviews):
    """SC-003. The old template filtered `rating >= 4`, invisibly."""
    html = _read(site_with_reviews, "testimonials/index.html")
    assert "Took three days longer than quoted." in html, (
        "the 1-star review was dropped; criticism is part of the evidence")


def test_every_archived_review_appears(site_with_reviews):
    """SC-004."""
    html = _read(site_with_reviews, "testimonials/index.html")
    for r in FIXTURE["reviews"]:
        assert r["text"] in html, f"missing from /testimonials/: {r['text']!r}"


def test_the_page_states_how_much_of_the_total_it_holds(site_with_reviews):
    """SC-007. 'We hold 3 of 549' is a different claim from 'there are 3'."""
    html = _read(site_with_reviews, "testimonials/index.html")
    assert "549" in html
    assert re.search(r"\b3\b", html), "the retrieved count is not stated"


def test_the_structured_data_parses_as_an_object(site_with_reviews):
    """It shipped once as an escaped STRING — valid JSON, useless structured
    data. `safeJS` is what stops Hugo escaping it."""
    ld = _ld(_read(site_with_reviews, "index.html"))
    assert isinstance(ld, dict)
    assert ld["@type"] == "LocalBusiness"


def test_the_aggregate_rating_matches_the_archive(site_with_reviews):
    """SC-005. Structured data that disagrees with the visible page is the
    machine-readable version of lying, and Google treats it as that."""
    agg = _ld(_read(site_with_reviews, "index.html")).get("aggregateRating")
    assert agg, "no AggregateRating — 549 reviews still produce no stars in search"
    assert float(agg["ratingValue"]) == FIXTURE["rating"]
    assert int(agg["reviewCount"]) == FIXTURE["user_ratings_total"]
