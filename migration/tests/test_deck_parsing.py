"""Golden-fixture tests for the weekly repair deck parser.

The fixture is the team's own deck, already tracked in this repo:
`migration/wp-export/wp-content/uploads/2022/02/Repair-1.1.7.pptx`. Every expectation below
was read out of that file during planning, so these tests describe a real format rather than
an assumed one.

Written before `tools/deck_to_posts.py` exists (Constitution I).
"""
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "tools"))

DECK = REPO_ROOT / "migration/wp-export/wp-content/uploads/2022/02/Repair-1.1.7.pptx"

# Slides 1-5 are boilerplate capability slides ("WE REPAIR" + a list of services); slides
# 6-9 are the actual repairs.
EXPECTED = {
    6: {
        "title": "Redmi Note 7 – Charging port Replacement",
        "before_image": "image5.jpg",
        "after_image": "image6.jpg",
        "before_caption": "The device was given to us with no charging condition",
        "after_caption": "We had Replaced the Charging port and tested it is charging or not",
    },
    7: {
        # NOTE: image8 is on the LEFT and image7 on the RIGHT. Filename order is not
        # before/after order — only x-position is.
        "title": "Realme 9 Power – Display Combo Replacement",
        "before_image": "image8.jpg",
        "after_image": "image7.jpg",
        "before_caption": "The device was given to us with broken display",
        "after_caption": "We had Replaced the Display Combo and made it functioning",
    },
    8: {
        "title": "iPhone 7 – Display Combo Replacement",
        "before_image": "image10.jpg",
        "after_image": "image9.jpg",
        "before_caption": "The iPhone was given to us with the display combo damaged condition",
        "after_caption": "We had Replaced the Display Combo and made it functioning",
    },
    9: {
        "title": "Moto G5s Plus – Touch Glass Replacement",
        "before_image": "image11.png",
        "after_image": "image12.png",
        "before_caption": "The phone was given to us with touch not working",
        "after_caption": "We had Replaced the Touch Glass and got it working",
    },
}


@pytest.fixture(scope="module")
def parsed():
    if not DECK.is_file():
        pytest.fail(f"fixture deck missing: {DECK}")
    import deck_to_posts
    return deck_to_posts.parse_deck(DECK)


# SC-001 ----------------------------------------------------------------------
def test_only_repair_slides_are_taken(parsed):
    assert [r.slide for r in parsed.repairs] == [6, 7, 8, 9]


def test_boilerplate_slides_are_skipped_with_reasons(parsed):
    assert [s.slide for s in parsed.skipped] == [1, 2, 3, 4, 5]
    for s in parsed.skipped:
        assert s.reason, f"slide {s.slide} skipped with no reason recorded"


# SC-002 : the trap ------------------------------------------------------------
@pytest.mark.parametrize("slide", [6, 7, 8, 9])
def test_before_after_assigned_by_position_not_filename(parsed, slide):
    r = next(r for r in parsed.repairs if r.slide == slide)
    assert r.before_image.name == EXPECTED[slide]["before_image"]
    assert r.after_image.name == EXPECTED[slide]["after_image"]


def test_slides_7_and_8_have_inverted_filename_order(parsed):
    """Explicit regression guard: sorting media by name would silently swap before/after
    on these two slides, which is the kind of error nobody notices in a thumbnail."""
    for slide in (7, 8):
        r = next(r for r in parsed.repairs if r.slide == slide)
        before_n = int("".join(c for c in r.before_image.name if c.isdigit()))
        after_n = int("".join(c for c in r.after_image.name if c.isdigit()))
        assert before_n > after_n, (
            f"slide {slide}: expected the before image to have the HIGHER media number "
            f"(that is what makes it a useful trap); got {r.before_image.name} / "
            f"{r.after_image.name}"
        )


# SC-003 ----------------------------------------------------------------------
@pytest.mark.parametrize("slide", [6, 7, 8, 9])
def test_title_and_captions_extracted_verbatim(parsed, slide):
    r = next(r for r in parsed.repairs if r.slide == slide)
    exp = EXPECTED[slide]
    assert r.title == exp["title"]
    assert r.before_caption == exp["before_caption"]
    assert r.after_caption == exp["after_caption"]


def test_footer_furniture_never_leaks_into_fields(parsed):
    """Deck version, page number, slide date and the company footer are furniture."""
    junk = ("1.1.7", "Gadjoy Repair Services", "10-03-2021", "20-02-2022")
    for r in parsed.repairs:
        for field in (r.title, r.before_caption, r.after_caption):
            for bad in junk:
                assert bad not in field, f"slide {r.slide}: furniture {bad!r} leaked into {field!r}"


def test_before_after_labels_are_not_mistaken_for_captions(parsed):
    for r in parsed.repairs:
        assert r.before_caption.strip() not in ("Before", "After")
        assert r.after_caption.strip() not in ("Before", "After")


# SC-005 : a slide may carry a video ------------------------------------------
def test_video_slide_does_not_break_the_run(parsed):
    """Slide 9 has a videoFile alongside its two pictures; it must parse like any other repair."""
    r = next(r for r in parsed.repairs if r.slide == 9)
    assert r.title == EXPECTED[9]["title"]
    assert hasattr(r, "video"), "Repair must expose a `video` attribute, even if None"


def test_the_video_is_actually_found(parsed):
    """The original assertion here was `hasattr(r, "video")` — which passes even when the
    attribute is permanently None, and it was: `<a:videoFile>` lives in the DrawingML
    namespace and the parser looked in presentationml, so no video was ever detected. A test
    that cannot distinguish "found nothing" from "looked in the wrong place" is not a test."""
    r = next(r for r in parsed.repairs if r.slide == 9)
    assert r.video is not None, "slide 9 carries a video; the parser must find it"
    assert r.video.name.lower().endswith((".mp4", ".mov", ".m4v"))
    assert len(r.video.data) > 10_000, "must be the real media, not an empty placeholder"


def test_slides_without_video_report_none(parsed):
    for r in parsed.repairs:
        if r.slide != 9:
            assert r.video is None, f"slide {r.slide} has no video but one was reported"


# SC-004 : format drift must be loud -----------------------------------------
def test_repair_shaped_slide_without_a_title_raises():
    """Publication is unattended, so a slide that looks like a repair but cannot be read
    must stop the run rather than be quietly dropped."""
    import deck_to_posts
    with pytest.raises(deck_to_posts.DeckFormatError):
        deck_to_posts.build_repair(
            slide=3,
            texts=[("Before", 1_000_000, 1_400_000), ("After", 7_000_000, 1_400_000)],
            pictures=[("a.jpg", 2_000_000), ("b.jpg", 7_000_000)],
            slide_width=12_192_000,
            video=None,
        )


def test_images_are_returned_as_real_bytes(parsed):
    """The parser must hand back the embedded original, not a path into the zip."""
    r = parsed.repairs[0]
    assert isinstance(r.before_image.data, bytes) and len(r.before_image.data) > 1000
    assert isinstance(r.after_image.data, bytes) and len(r.after_image.data) > 1000
