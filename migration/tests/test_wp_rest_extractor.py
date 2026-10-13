"""Extraction, front matter and migration-driver tests for wp_rest_to_hugo.py.

test_conversion.py covers normalize_media_url and html_to_markdown. Everything
downstream of those — taxonomy reading, banner selection, front matter, the
pagination loop and migrate() itself — was untested, which is 92 of this
module's 160 statements.

This is the module the constitution's Principles II-V are about: it is the only
thing that may produce content, and the previous migration silently corrupted
1,500+ posts. The assertions here are mostly "the output contains exactly what
the source contained", because the failure mode is fabrication, not a crash.

SAFETY: migrate(clean=True) calls shutil.rmtree on CONTENT_BLOG_DIR, which in a
real checkout is content/blog — the authoritative source. Every test that
reaches migrate() redirects all four module constants at tmp_path first. The
`sandbox` fixture asserts the redirect took effect before anything destructive
runs, because a typo'd monkeypatch here deletes the site's content.

Order, recorded honestly (CON-PROC-005): written after the module existed. Each
guard names the mutation that proves it.
"""
import sys

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "migration" / "scripts"))


@pytest.fixture(scope="module")
def wp():
    import wp_rest_to_hugo
    return wp_rest_to_hugo


@pytest.fixture
def uploads(wp, tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(wp, "STATIC_UPLOADS_DIR", d)
    return d


@pytest.fixture
def sandbox(wp, tmp_path, monkeypatch, uploads):
    """Redirect every path constant, then PROVE the redirect took."""
    content = tmp_path / "content"
    blog = content / "blog"
    monkeypatch.setattr(wp, "CONTENT_DIR", content)
    monkeypatch.setattr(wp, "CONTENT_BLOG_DIR", blog)
    monkeypatch.setattr(wp, "MISSING_MEDIA_REPORT", tmp_path / "missing.txt")

    assert str(wp.CONTENT_BLOG_DIR).startswith(str(tmp_path)), \
        "refusing to run: CONTENT_BLOG_DIR still points outside the sandbox"
    assert str(wp.CONTENT_DIR).startswith(str(tmp_path))
    return content, blog


def post(**over):
    """A minimal _embed'd WP REST post."""
    base = {
        "slug": "screen-repair",
        "date": "2025-02-14T10:30:00",
        "title": {"rendered": "Screen &amp; Glass Repair"},
        "content": {"rendered": "<p>Body text.</p>"},
        "excerpt": {"rendered": "<p>A short excerpt.</p>"},
        "_embedded": {},
    }
    base.update(over)
    return base


def terms(*specs):
    return {"wp:term": [[{"taxonomy": tax, "slug": slug, "name": name}
                         for tax, slug, name in specs]]}


# --- prune_missing_media -----------------------------------------------------

def test_a_dangling_image_ref_is_dropped_and_reported(wp, uploads):
    md = "Before\n\n![shot](/img/uploads/2025/02/gone.png)\n\nAfter"

    out, missing = wp.prune_missing_media(md, uploads)

    assert missing == ["/img/uploads/2025/02/gone.png"]
    assert "gone.png" not in out
    assert "Before" in out and "After" in out


def test_a_present_image_ref_is_kept(wp, uploads):
    (uploads / "2025").mkdir(parents=True)
    (uploads / "2025" / "here.png").write_bytes(b"x")
    md = "![shot](/img/uploads/2025/here.png)"

    out, missing = wp.prune_missing_media(md, uploads)

    assert missing == []
    assert out == md


def test_a_dangling_video_ref_is_dropped(wp, uploads):
    md = 'Text\n\n<video controls src="/img/uploads/2023/07/clip.mp4"></video>\n\nMore'

    out, missing = wp.prune_missing_media(md, uploads)

    assert missing == ["/img/uploads/2023/07/clip.mp4"]
    assert "<video" not in out


def test_a_dropped_ref_is_never_replaced_by_a_substitute(wp, uploads):
    """Principle II/III: absent in the source means absent in the output. A
    placeholder image here would be indistinguishable from a real one later.

    Mutation proving this: have the substitution insert any replacement text and
    the assertion below fails."""
    (uploads / "real.png").write_bytes(b"x")
    md = "![a](/img/uploads/missing.png)\n\n![b](/img/uploads/real.png)"

    out, _ = wp.prune_missing_media(md, uploads)

    assert out == "![b](/img/uploads/real.png)"


def test_blank_runs_left_by_pruning_are_collapsed(wp, uploads):
    md = "A\n\n![x](/img/uploads/a.png)\n\n![y](/img/uploads/b.png)\n\nB"

    out, missing = wp.prune_missing_media(md, uploads)

    assert len(missing) == 2
    assert "\n\n\n" not in out


# --- taxonomy ----------------------------------------------------------------

def test_terms_are_read_as_stored_not_derived(wp):
    """Principle III: taxonomy is read as stored, never inferred from the title."""
    p = post(_embedded=terms(("category", "water-damage", "Water Damage"),
                             ("post_tag", "iphone-12", "iPhone 12")))

    assert wp._terms(p, "category") == [{"slug": "water-damage", "name": "Water Damage"}]
    assert wp._terms(p, "post_tag") == [{"slug": "iphone-12", "name": "iPhone 12"}]


def test_front_matter_stores_term_slugs_not_display_names(wp, uploads):
    """Mutation proving this: return t["name"] instead of t["slug"] in
    build_front_matter and the categories become display names.

    Asserting _terms() alone does NOT cover this — _terms returns both fields,
    so the mutation lives entirely in build_front_matter's choice between them.
    The first version of this file tested only _terms and the mutation passed.

    Hugo links taxonomies by slug, so a display name here is the '&' ->
    double-hyphen mismatch that 404'd the category archives."""
    p = post(_embedded=terms(("category", "repair-maintenance", "Repair & Maintenance"),
                             ("post_tag", "iphone-12", "iPhone 12")))

    fm = wp.build_front_matter(p)

    assert fm["categories"] == ["repair-maintenance"]
    assert fm["tags"] == ["iphone-12"]


def test_term_names_are_html_unescaped(wp):
    p = post(_embedded=terms(("category", "repair-maintenance", "Repair &amp; Maintenance")))

    assert wp._terms(p, "category")[0]["name"] == "Repair & Maintenance"


def test_a_post_with_no_terms_yields_empty_lists_not_a_guess(wp, uploads):
    """Guessing a category from the title is explicitly forbidden."""
    fm = wp.build_front_matter(post())

    assert fm["categories"] == []
    assert fm["tags"] == []


# --- banner selection --------------------------------------------------------

def test_featured_image_is_used_when_it_exists_on_disk(wp, uploads):
    (uploads / "feat.png").write_bytes(b"x")
    p = post(_embedded={"wp:featuredmedia": [
        {"source_url": "https://gadjoy.in/wp-content/uploads/feat.png"}]})

    assert wp._card_banner(p) == "/img/uploads/feat.png"


def test_a_featured_image_missing_from_disk_falls_back_to_content(wp, uploads):
    """Mutation proving this: drop the _exists(feat) check and the banner points
    at a file that was never in the backup — a guaranteed broken thumbnail."""
    (uploads / "inline.png").write_bytes(b"x")
    p = post(
        content={"rendered": '<p><img src="/img/uploads/inline.png"></p>'},
        _embedded={"wp:featuredmedia": [
            {"source_url": "https://gadjoy.in/wp-content/uploads/absent.png"}]},
    )

    assert wp._card_banner(p) == "/img/uploads/inline.png"


def test_the_first_resolving_content_image_wins(wp, uploads):
    (uploads / "second.png").write_bytes(b"x")
    p = post(content={"rendered":
                      '<img src="/img/uploads/first.png"><img src="/img/uploads/second.png">'})

    assert wp._card_banner(p) == "/img/uploads/second.png"


def test_no_resolvable_image_means_no_banner_key(wp, uploads):
    """Absent in the source means absent in the output — not an empty string,
    which the theme would render as a broken img."""
    fm = wp.build_front_matter(post(content={"rendered": "<p>text only</p>"}))

    assert "banner" not in fm


# --- front matter ------------------------------------------------------------

def test_the_alias_preserves_the_broken_live_blog_path(wp, uploads):
    """Principle IV, URL parity. Mutation proving this: drop the aliases entry
    and every old inbound /blog/ link 404s. This is a real business's live site."""
    fm = wp.build_front_matter(post())

    assert fm["aliases"] == ["/blog/2025/02/14/screen-repair/"]


def test_the_title_is_unescaped_as_stored(wp, uploads):
    assert wp.build_front_matter(post())["title"] == "Screen & Glass Repair"


def test_the_date_is_the_source_date_untouched(wp, uploads):
    assert wp.build_front_matter(post())["date"] == "2025-02-14T10:30:00"


def test_an_excerpt_becomes_both_description_and_summary(wp, uploads):
    fm = wp.build_front_matter(post())

    assert fm["description"] == "A short excerpt."
    assert fm["summary"] == "A short excerpt."


def test_an_empty_excerpt_produces_no_description_key(wp, uploads):
    """Mutation proving this: set the keys unconditionally and every post gains
    an empty description — a fabricated field that later reads as real."""
    fm = wp.build_front_matter(post(excerpt={"rendered": "   <p></p>  "}))

    assert "description" not in fm
    assert "summary" not in fm


def test_posts_are_never_drafts(wp, uploads):
    assert wp.build_front_matter(post())["draft"] is False


# --- render_post -------------------------------------------------------------

def test_the_post_path_follows_the_permalink_structure(wp, sandbox, uploads):
    _, blog = sandbox

    path, content, missing, terms_out = wp.render_post(post())

    assert path == blog / "2025" / "02" / "14" / "screen-repair" / "index.md"
    assert content.startswith("---\n")
    assert "Body text." in content
    assert missing == []


def test_rendered_output_carries_no_wp_comment_residue(wp, sandbox, uploads):
    """Principle V."""
    _, content, _, _ = wp.render_post(post(content={
        "rendered": "<!-- wp:paragraph --><p>Hello.</p><!-- /wp:paragraph -->"}))

    assert "wp:" not in content
    assert "Hello." in content


# --- write_term_pages --------------------------------------------------------

def test_term_pages_carry_the_real_display_name(wp, sandbox):
    content, _ = sandbox

    wp.write_term_pages({"categories": {"water-damage": "Water & Damage"}, "tags": {}})

    page = content / "categories" / "water-damage" / "_index.md"
    assert "Water & Damage" in page.read_text()


# --- fetch_all_posts ---------------------------------------------------------

class Resp:
    def __init__(self, payload, status=200, pages=1):
        self._p = payload
        self.status_code = status
        self.headers = {"X-WP-TotalPages": str(pages)}

    def json(self):
        return self._p


def test_pagination_follows_the_total_pages_header(wp, monkeypatch):
    """Mutation proving this: stop after the first request and only the first
    100 posts migrate — the corpus is ~1,500, so this silently drops most of it."""
    pages = {1: [{"slug": "a"}], 2: [{"slug": "b"}], 3: [{"slug": "c"}]}
    seen = []

    def fake_get(url, params=None, timeout=None):
        seen.append(params["page"])
        return Resp(pages[params["page"]], pages=3)

    monkeypatch.setattr(wp.requests, "get", fake_get)

    assert [p["slug"] for p in wp.fetch_all_posts("http://x")] == ["a", "b", "c"]
    assert seen == [1, 2, 3]


def test_a_non_200_stops_the_fetch_without_crashing(wp, monkeypatch):
    monkeypatch.setattr(wp.requests, "get",
                        lambda url, params=None, timeout=None: Resp([], status=500))
    assert wp.fetch_all_posts("http://x") == []


def test_an_empty_page_stops_the_fetch(wp, monkeypatch):
    monkeypatch.setattr(wp.requests, "get",
                        lambda url, params=None, timeout=None: Resp([], pages=9))
    assert wp.fetch_all_posts("http://x") == []


def test_a_non_list_payload_is_treated_as_the_end(wp, monkeypatch):
    """A WP error object is a dict; iterating it would migrate its keys as posts."""
    monkeypatch.setattr(wp.requests, "get",
                        lambda url, params=None, timeout=None: Resp({"code": "rest_error"}))
    assert wp.fetch_all_posts("http://x") == []


# --- migrate -----------------------------------------------------------------

def test_migrate_writes_a_bundle_per_post_and_term_pages(wp, sandbox, uploads, monkeypatch):
    content, blog = sandbox
    monkeypatch.setattr(wp, "fetch_all_posts", lambda base: [
        post(_embedded=terms(("category", "water-damage", "Water Damage"))),
        post(slug="battery", date="2024-11-02T09:00:00",
             _embedded=terms(("post_tag", "iphone", "iPhone"))),
    ])

    n = wp.migrate("http://x", clean=False)

    assert n == 2
    assert (blog / "2025" / "02" / "14" / "screen-repair" / "index.md").is_file()
    assert (blog / "2024" / "11" / "02" / "battery" / "index.md").is_file()
    assert (content / "categories" / "water-damage" / "_index.md").is_file()
    assert (content / "tags" / "iphone" / "_index.md").is_file()


def test_clean_false_leaves_existing_content_in_place(wp, sandbox, uploads, monkeypatch):
    """Mutation proving this: ignore the clean flag and rmtree unconditionally —
    the keeper file below disappears. content/blog is the authoritative source
    (CLAUDE.md), so an unguarded rmtree here is the worst defect in the repo."""
    _, blog = sandbox
    keeper = blog / "keep-me.md"
    blog.mkdir(parents=True)
    keeper.write_text("hand-written")
    monkeypatch.setattr(wp, "fetch_all_posts", lambda base: [])

    wp.migrate("http://x", clean=False)

    assert keeper.read_text() == "hand-written"


def test_clean_true_removes_the_previous_output(wp, sandbox, uploads, monkeypatch):
    _, blog = sandbox
    blog.mkdir(parents=True)
    (blog / "stale.md").write_text("from a previous run")
    monkeypatch.setattr(wp, "fetch_all_posts", lambda base: [])

    wp.migrate("http://x", clean=True)

    assert not (blog / "stale.md").exists()
    assert blog.is_dir(), "the directory itself must be recreated"


def test_dropped_media_is_reported_to_a_file(wp, sandbox, uploads, monkeypatch, capsys):
    """Principle V: the dropped refs are reported, never silently swallowed."""
    monkeypatch.setattr(wp, "fetch_all_posts", lambda base: [
        post(content={"rendered": '<p><img src="/img/uploads/absent.png"></p>'})])

    wp.migrate("http://x", clean=False)

    report = wp.MISSING_MEDIA_REPORT.read_text()
    assert "screen-repair" in report
    assert "/img/uploads/absent.png" in report
    assert "Dropped 1 dangling media refs" in capsys.readouterr().out


def test_no_report_file_when_nothing_was_dropped(wp, sandbox, uploads, monkeypatch):
    monkeypatch.setattr(wp, "fetch_all_posts", lambda base: [
        post(content={"rendered": "<p>clean</p>"})])

    wp.migrate("http://x", clean=False)

    assert not wp.MISSING_MEDIA_REPORT.exists()
