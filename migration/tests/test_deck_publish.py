"""Generation tests: deck repairs → Hugo post bundles, with the privacy interlock.

Written before the generator exists (Constitution I). The parser is covered separately in
`test_deck_parsing.py`; this file is about what gets *written into the site*.

The interlock is the important part. Repair photos have already been shown to publish
customer identifiers — 229 images were redacted in PR #16 — and a deck coming straight off
the bench is the same source. So nothing may reach `static/` un-redacted, and that guard is
mutation-tested rather than assumed.
"""
import re
import sys
from pathlib import Path

import pytest

from conftest import CONTENT_BLOG_DIR, REPO_ROOT, iter_generated_posts

sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "migration" / "scripts"))

DECK = REPO_ROOT / "migration/wp-export/wp-content/uploads/2022/02/Repair-1.1.7.pptx"
PII_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "about-screen-with-identifiers.png"
REAL_CATEGORIES = {p.name for p in (REPO_ROOT / "content" / "categories").iterdir() if p.is_dir()}


@pytest.fixture(scope="module")
def dtp():
    import deck_to_posts
    return deck_to_posts


@pytest.fixture(scope="module")
def existing_slugs():
    return {fm.get("slug") for _p, fm, _b in iter_generated_posts() if fm.get("slug")}


# --- slugs (SC-010) -----------------------------------------------------------
@pytest.mark.parametrize("title,expected", [
    ("Redmi Note 7 – Charging port Replacement", "redmi-note-7-charging-port-replacement"),
    ("iPhone 7 – Display Combo Replacement", "iphone-7-display-combo-replacement"),
    ("Moto G5s Plus – Touch Glass Replacement", "moto-g5s-plus-touch-glass-replacement"),
])
def test_slugify(dtp, title, expected):
    assert dtp.slugify(title) == expected


def test_slug_is_deduped_against_existing_posts(dtp):
    existing = {"redmi-4-dead-condition", "redmi-4-dead-condition-2"}
    assert dtp.unique_slug("redmi-4-dead-condition", existing) == "redmi-4-dead-condition-3"
    assert dtp.unique_slug("brand-new-slug", existing) == "brand-new-slug"


def test_generated_slugs_never_collide_with_the_migrated_corpus(dtp, existing_slugs):
    """1,508 posts already exist; a colliding slug would make two repairs fight for one URL."""
    parsed = dtp.parse_deck(DECK)
    taken = set(existing_slugs)
    for r in parsed.repairs:
        s = dtp.unique_slug(dtp.slugify(r.title), taken)
        assert s not in existing_slugs
        taken.add(s)


# --- categories (FR-013) ------------------------------------------------------
def test_categories_are_only_ever_real_slugs(dtp):
    parsed = dtp.parse_deck(DECK)
    for r in parsed.repairs:
        cats = dtp.categories_for(r.title)
        assert cats, f"{r.title}: no categories"
        for c in cats:
            assert c in REAL_CATEGORIES, (
                f"{c!r} is not an existing category — inventing taxonomy is forbidden "
                f"(Principle III) and test_taxonomy_is_real would reject it"
            )


def test_unmapped_work_falls_back_to_repair(dtp):
    assert dtp.categories_for("Something Entirely Unfamiliar – Frobnicating") == ["repair"]


def test_known_work_is_classified(dtp):
    assert "display-and-glass-replacement" in dtp.categories_for("iPhone 7 – Display Combo Replacement")
    assert "mobiles" in dtp.categories_for("Redmi Note 7 – Charging port Replacement")


# --- dates (FR-009) -----------------------------------------------------------
def test_post_date_comes_from_the_issue_not_the_slide(dtp):
    """Every repair slide in the reference deck says 10-03-2021, in a deck dated 20-02-2022.
    It is an unmaintained placeholder and must never become a post's URL."""
    parsed = dtp.parse_deck(DECK)
    post = dtp.build_post(parsed.repairs[0], date="2026-08-08", issue=42, existing_slugs=set())
    assert str(post.front_matter["date"]).startswith("2026-08-08")
    assert "2021" not in str(post.front_matter["date"])


# --- post shape (FR-012, FR-016, FR-018) --------------------------------------
def test_post_front_matter_shape(dtp):
    parsed = dtp.parse_deck(DECK)
    post = dtp.build_post(parsed.repairs[0], date="2026-08-08", issue=42, existing_slugs=set())
    fm = post.front_matter
    assert fm["origin"] == "deck", "needed by the migrated-count invariant"
    assert fm["deck_issue"] == 42
    assert fm["aliases"] == [], "a new repair never had a legacy /blog/ URL to rescue"
    assert fm["banner"].startswith("/img/uploads/"), "cards need a thumbnail"
    assert "<" not in fm["summary"], "summary must be plaintext"
    assert fm["description"] and fm["description"] != "Before After"
    assert fm["draft"] is False


def test_post_body_has_before_and_after_with_captions(dtp):
    parsed = dtp.parse_deck(DECK)
    r = parsed.repairs[0]
    post = dtp.build_post(r, date="2026-08-08", issue=42, existing_slugs=set())
    assert "## Before" in post.body and "## After" in post.body
    assert r.before_caption in post.body and r.after_caption in post.body
    assert post.body.index("## Before") < post.body.index("## After")


def test_image_paths_are_deterministic_and_self_describing(dtp):
    parsed = dtp.parse_deck(DECK)
    post = dtp.build_post(parsed.repairs[0], date="2026-08-08", issue=42, existing_slugs=set())
    keys = sorted(post.images)
    assert any(k.endswith("-before.webp") for k in keys)
    assert any(k.endswith("-after.webp") for k in keys)
    for k in keys:
        assert k.startswith("static/img/uploads/2026/08/")


# --- the privacy interlock (SC-008) -------------------------------------------
def test_identifiers_are_redacted_before_an_image_is_written(dtp, tmp_path):
    """An About-screen photo must come out with its identifiers destroyed."""
    from device_identifiers import find_identifiers, ocr_words

    raw = PII_FIXTURE.read_bytes()
    before_hits = dtp.detect_identifiers(raw, PII_FIXTURE.name)
    assert before_hits, "precondition: the fixture must contain detectable identifiers"

    cleaned, removed = dtp.redact_bytes(raw, PII_FIXTURE.name)
    assert removed, "interlock reported nothing removed"
    assert cleaned != raw, "image was not modified"

    tmp = tmp_path / "chk.png"
    tmp.write_bytes(cleaned)
    text, words = ocr_words(tmp)
    hard = [h for h in find_identifiers(text, words)
            if h["kind"] in ("long_digit_run", "mac_address")]
    assert not hard, f"identifier values survived redaction: {hard}"


def test_build_post_runs_every_image_through_the_interlock(dtp, monkeypatch):
    """The guard must be wired in, not merely available.

    Asserted by counting calls: a future refactor that writes images straight from the deck
    would leave this at zero and fail here.
    """
    calls = []
    real = dtp.redact_bytes

    def spy(data, name):
        calls.append(name)
        return real(data, name)

    monkeypatch.setattr(dtp, "redact_bytes", spy)
    parsed = dtp.parse_deck(DECK)
    dtp.build_post(parsed.repairs[0], date="2026-08-08", issue=42, existing_slugs=set())
    assert len(calls) == 2, f"expected both images redacted, saw {calls}"


# --- idempotence (SC-007) -----------------------------------------------------
def test_republishing_the_same_deck_adds_nothing(dtp, tmp_path):
    first = dtp.publish_deck(DECK, date="2026-08-08", issue=42, out_root=tmp_path)
    assert len(first.published) == 4
    second = dtp.publish_deck(DECK, date="2026-08-08", issue=42, out_root=tmp_path)
    assert second.published == [], "a second run must not duplicate posts"
    assert len(second.already_present) == 4


def test_a_slide_video_is_reported_not_silently_dropped(dtp, tmp_path):
    """FR-010: embed it, or skip it with a recorded reason. It was being skipped with NO
    reason — and in fact never detected at all. Videos stay unpublished because the privacy
    interlock cannot scan frames, but the team must be told, or the same About-screen habit
    simply moves to video."""
    report = dtp.publish_deck(DECK, date="2026-09-19", issue=99, out_root=tmp_path)
    assert report.skipped_videos, "slide 9 has a video; the report must say it was held back"
    assert any("slide 9" in v for v in report.skipped_videos)


def test_video_skip_reaches_the_issue_comment(dtp):
    import publish_decks

    class R:
        published, already_present, skipped, redactions, resurfaced_slugs = [], [], [], {}, []
        skipped_videos = ["some-slug (slide 9)"]

    text = "\n".join(publish_decks.report_lines("week.pptx", R()))
    assert "video" in text.lower() and "slide 9" in text


def test_publish_reports_skipped_slides_with_reasons(dtp, tmp_path):
    report = dtp.publish_deck(DECK, date="2026-08-08", issue=42, out_root=tmp_path)
    assert len(report.skipped) == 5
    assert all(s.reason for s in report.skipped)


# --- integration: generated posts must satisfy the REAL invariants (SC-006) ----
def test_generated_posts_satisfy_the_real_content_invariants(dtp, tmp_path, wp_terms):
    """Run the actual acceptance functions over freshly generated posts.

    Asserting "the front matter looks right" is not the same as passing the gate the site is
    held to, so the gate itself is invoked here.
    """
    import test_invariants as inv

    report = dtp.publish_deck(DECK, date="2026-08-08", issue=42, out_root=tmp_path)
    posts = [(Path(p.bundle_path), p.front_matter, p.body) for p in report.published]
    assert len(posts) == 4

    inv.test_no_wordpress_artifacts(posts)
    inv.test_front_matter_complete(posts)
    inv.test_url_preservation_via_aliases(posts)     # exempt as origin: deck, must not raise
    inv.test_summary_is_plaintext(posts)
    inv.test_taxonomy_is_real(posts, wp_terms)
    inv.test_taxonomy_term_pages_exist_with_titles(posts)

    # The banner must be one of the images this run actually wrote (the real
    # test_card_banner_present_and_resolves resolves against the repo's static tree, which a
    # tmp_path run has not populated).
    for post in report.published:
        written = {"/" + k.split("static/", 1)[1] for k in post.images}
        assert post.front_matter["banner"] in written


def test_every_generated_image_lands_where_the_markdown_points(dtp, tmp_path):
    report = dtp.publish_deck(DECK, date="2026-08-08", issue=42, out_root=tmp_path)
    for post in report.published:
        md = tmp_path / post.bundle_path
        body = md.read_text(encoding="utf-8")
        for ref in re.findall(r"/img/uploads/[^\s)\"']+", body):
            assert (tmp_path / "static" / ref.lstrip("/")).is_file(), f"dangling {ref}"
