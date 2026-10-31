"""tools/fetch_reviews.py — the archive (spec 015, FR-001/006/007).

Written before the module exists (Principle I). Expected red.

THE CENTRAL GUARD IS test_a_smaller_response_never_shrinks_the_archive.
Everything else here is plumbing. The point of this feature is that the reviews
survive Google removing them, and an archive that can be shrunk by one bad API
response is a cache with extra steps — it would lose the evidence at precisely
the moment the evidence mattered.
"""
import json
import sys

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "tools"))
fr = pytest.importorskip("fetch_reviews", reason="not implemented yet (spec 015)")


def review(rid, rating=5, text="Great work", author="A", when=1700000000):
    return {"time": when, "rating": rating, "text": text,
            "author_name": author, "author_url": f"https://g/{rid}",
            "relative_time_description": "a month ago"}


def payload(reviews, rating=4.7, total=549):
    return {"status": "OK", "result": {
        "rating": rating, "user_ratings_total": total, "reviews": reviews,
        "url": "https://maps.google.com/x"}}


# --- the merge rule ----------------------------------------------------------

def test_a_smaller_response_never_shrinks_the_archive(tmp_path):
    """FR-007 / SC-006. The whole feature rests on this.

    Mutation proving it: replace the union with a plain assignment and this
    fails — the archive drops to one review and 44 years of goodwill with it.
    """
    out = tmp_path / "reviews.json"
    fr.write_archive(out, fr.build_archive(payload(
        [review("a"), review("b"), review("c")]), existing=None))
    assert len(json.loads(out.read_text())["reviews"]) == 3

    existing = json.loads(out.read_text())
    fr.write_archive(out, fr.build_archive(payload([review("a")]), existing=existing))

    kept = json.loads(out.read_text())["reviews"]
    assert len(kept) == 3, (
        f"the archive shrank to {len(kept)}; a thin API response must never "
        f"delete reviews already held")


def test_a_new_review_is_added_to_the_existing_archive(tmp_path):
    out = tmp_path / "reviews.json"
    fr.write_archive(out, fr.build_archive(payload([review("a")]), existing=None))
    existing = json.loads(out.read_text())
    fr.write_archive(out, fr.build_archive(payload([review("b")]), existing=existing))

    assert len(json.loads(out.read_text())["reviews"]) == 2


def test_the_longer_text_wins_when_a_review_reappears(tmp_path):
    """Google sometimes returns a truncated form. Keeping the longer text means
    the archive only ever gains detail."""
    out = tmp_path / "reviews.json"
    fr.write_archive(out, fr.build_archive(
        payload([review("a", text="They fixed my dead Redmi in a day, superb")]), existing=None))
    existing = json.loads(out.read_text())
    fr.write_archive(out, fr.build_archive(payload([review("a", text="Superb")]), existing=existing))

    texts = [r["text"] for r in json.loads(out.read_text())["reviews"]]
    assert texts == ["They fixed my dead Redmi in a day, superb"]


# --- honesty about the gap ---------------------------------------------------

def test_the_archive_records_how_much_it_holds_versus_the_total(tmp_path):
    """FR-006 / SC-007. 'We hold 5 of 549' is a different claim from 'there are
    5', and the file must make which one it is unmistakable (CON-DATA-002)."""
    arch = fr.build_archive(payload([review("a"), review("b")], total=549), existing=None)

    assert arch["user_ratings_total"] == 549
    assert arch["reviews_retrieved"] == 2
    assert "Business Profile" in arch["retrieval_limit"], (
        "the archive does not say WHY it is partial; a future reader will take "
        "it for the whole set")


def test_criticism_is_archived_not_filtered(tmp_path):
    """FR-003. The old template dropped everything under 4 stars."""
    arch = fr.build_archive(payload([review("a", rating=1, text="Took too long"),
                                     review("b", rating=5)]), existing=None)
    ratings = sorted(r["rating"] for r in arch["reviews"])

    assert ratings == [1, 5], "a 1-star review was dropped on the way into the archive"


# --- refusing bad input ------------------------------------------------------

def test_a_non_ok_response_is_refused(tmp_path):
    with pytest.raises(ValueError, match="status"):
        fr.build_archive({"status": "REQUEST_DENIED"}, existing=None)


def test_a_response_with_no_rating_is_refused(tmp_path):
    """Writing a zero rating over a good archive would be worse than failing."""
    with pytest.raises(ValueError):
        fr.build_archive({"status": "OK", "result": {"reviews": []}}, existing=None)


def test_a_refused_payload_leaves_the_existing_archive_untouched(tmp_path):
    out = tmp_path / "reviews.json"
    fr.write_archive(out, fr.build_archive(payload([review("a")]), existing=None))
    before = out.read_bytes()

    with pytest.raises(ValueError):
        fr.build_archive({"status": "OVER_QUERY_LIMIT"}, existing=None)

    assert out.read_bytes() == before


def test_reviews_are_ordered_newest_first(tmp_path):
    arch = fr.build_archive(payload([review("old", when=100), review("new", when=900)]),
                            existing=None)
    assert [r["time"] for r in arch["reviews"]] == [900, 100]
