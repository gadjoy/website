"""Build-output assertions: what the DEPLOYED HTML must contain.

`test_invariants.py` proves the Markdown *source* is correct. These tests prove the
*rendered site* is correct — which is the layer where every production bug this
project has actually shipped happened to live:

  - PR #6 / #7  the contact page silently fell back to the theme's post layout,
                because Hugo's template lookup differed between the dev and CI
                versions.                        -> test_contact_page_uses_project_layout
  - PR #10      the contact form posted to a placeholder Formspree ID that 404'd.
                                                 -> test_contact_form_endpoint_is_live
  - PR #13      the homepage stated a repair count derived from the number of blog
                posts, contradicting the résumé.  -> test_repair_claim_matches_config
  - (unnumbered) /2021/12/17/redmi-4-dead-condition/ shipped two 404ing images: the
                Markdown referenced `redmi-4-...webp` but the file on disk is
                `Redmi-4-...webp`. Case-blind on the author's macOS, 404 on the
                Linux Pages server.               -> test_internal_refs_resolve

Every one of those was found by a human looking at the live site. Each test below
is the guard that should have found it first.

Marked `build` (slow: needs the hugo binary and one full build).
"""
import re
from urllib.parse import unquote

import pytest

from conftest import CONTENT_BLOG_DIR, REPO_ROOT

pytestmark = pytest.mark.build

BASE_URL = "https://gadjoy.in"

# Pages that are hand-built by project layouts (not the migrated blog) and so carry
# all the bespoke markup. These are the ones worth asserting over in detail.
KEY_PAGES = [
    "index.html",
    "contact/index.html",
    "gallery/index.html",
    "services/we-repair/index.html",
    "services/we-build/index.html",
    "blog/index.html",
]

# Attribute values that are never local files.
_EXTERNAL = re.compile(r"^(?:[a-z]+:|//|#|data:)", re.I)

# `--minify` emits UNQUOTED attributes (`src=/img/x.webp`), so a quotes-only pattern
# matches almost nothing and every assertion built on it passes vacuously. That is
# not hypothetical: the first version of this file required quotes, silently found
# ~no references, and sailed past a deliberately broken image. Handle all three forms.
_ATTR_RE = re.compile(
    r"""(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I
)

# Inline <script>/<style> bodies contain things that look like attributes
# (`src=i[e].getAttribute(...)`); strip them or they become phantom broken links.
_CODE_BLOCK_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)

# Below this many distinct internal references, something has broken in extraction
# rather than the site genuinely having few links.
MIN_EXPECTED_REFS = 200


def _site_params():
    """params: from hugo.yaml. Read directly so the test is not circular —
    it compares rendered output against config, not against itself."""
    import yaml
    cfg = yaml.safe_load((REPO_ROOT / "hugo.yaml").read_text(encoding="utf-8"))
    return cfg.get("params", {}) or {}


def _has_attr(html, attr, value):
    """`--minify` strips attribute quotes, so `id="x"` ships as `id=x`. Match either."""
    return re.search(
        rf'{attr}\s*=\s*["\']?{re.escape(value)}["\'\s>]', html
    ) is not None


def _read(built_site, rel):
    p = built_site / rel
    assert p.exists(), f"expected page not built: {rel}"
    return p.read_text(encoding="utf-8", errors="ignore")


def _internal_targets(html):
    """Yield local-file targets referenced by this page, normalised to site-root
    relative paths. Absolute links to our own baseURL count as internal — Hugo
    emits those for canonical/og tags and menu items."""
    html = _CODE_BLOCK_RE.sub("", html)
    for groups in _ATTR_RE.findall(html):
        ref = next((g for g in groups if g), "").strip()
        if ref.startswith(BASE_URL):
            ref = ref[len(BASE_URL):] or "/"
        elif _EXTERNAL.match(ref):
            continue
        ref = ref.split("#", 1)[0].split("?", 1)[0]
        if not ref or not ref.startswith("/"):
            continue          # relative refs are rare here; skip rather than guess
        # Many migrated filenames contain en dashes and other non-ASCII, which Hugo
        # percent-encodes in the emitted HTML. Compare against the real filename.
        yield unquote(ref)


def _resolve(built_site, ref):
    """Map a site-root path to the file Hugo must have emitted for it."""
    rel = ref.lstrip("/")
    if rel == "" or ref.endswith("/"):
        return built_site / rel / "index.html"
    direct = built_site / rel
    if direct.is_file():
        return direct
    return built_site / rel / "index.html"      # extensionless pretty URL


# --- the four regression guards ----------------------------------------------
# Every page that Hugo resolves through a PROJECT layout rather than the theme's default.
# Each entry is (path, marker that only the project layout emits, what the page is).
#
# They are listed together because they fail the same way and by three DIFFERENT lookup
# mechanisms — `layout: contact` front matter, a section template under layouts/services/,
# and `layout: gallery` — so a Hugo upgrade can break one while the others keep working.
# Only contact was guarded before this, and only because it had already broken in production
# twice (#6/#7). The others were one Hugo bump away from the same silent 200.
PROJECT_LAYOUTS = [
    ("contact/index.html", "gj-contact-form", "contact form"),
    # svc-hero, not svc-steps: the first draft of this guard asserted on the step timeline and
    # failed We Build, which legitimately has no timeline. The marker has to be something the
    # LAYOUT always emits, not something one page happens to contain — otherwise the guard
    # reports a content difference as a layout failure and gets muted.
    ("services/we-repair/index.html", "svc-hero", "We Repair hero"),
    ("services/we-build/index.html", "svc-hero", "We Build hero"),
    # NOT gj-lightbox / gj-wall: custom_headers.html carries those same strings as JS
    # selectors on every page, so the marker survived in the HTML even with the gallery
    # layout deleted — the guard passed vacuously. Mutation testing caught it.
    # gadjoy-gallery-intro appears nowhere else.
    ("gallery/index.html", "gadjoy-gallery-intro", "gallery wall intro"),
]


@pytest.mark.parametrize("rel,marker,what", PROJECT_LAYOUTS,
                         ids=[p[0].split("/")[0] + "-" + p[0].split("/")[-2] if "/" in p[0][:-11]
                              else p[0].split("/")[0] for p in PROJECT_LAYOUTS])
def test_page_uses_its_project_layout(built_site, rel, marker, what):
    """A page that loses its project layout still builds and still returns HTTP 200 — it just
    silently renders as a plain blog post. Only asserting on bespoke markup catches that."""
    html = _read(built_site, rel)
    assert marker in html, (
        f"{rel} did not render its project layout — no sign of the {what}. It has fallen back "
        f"to the theme's default (the PR #6/#7 bug class), which still returns 200."
    )


def test_contact_page_uses_project_layout(built_site):
    """PR #6/#7: layouts/_default/contact.html must win the template lookup.

    When it lost, the page still built and still returned 200 — it just rendered
    as a plain blog post. So a build-success check cannot catch this; only
    asserting on bespoke markup can.
    """
    html = _read(built_site, "contact/index.html")
    assert _has_attr(html, "id", "gj-contact-form"), (
        "contact page did not render layouts/_default/contact.html — it has fallen "
        "back to the theme's default layout (the PR #6/#7 bug)"
    )
    assert _has_attr(html, "id", "gj-wa-send"), "contact page is missing the WhatsApp send button"


def test_contact_form_endpoint_is_live(built_site):
    """PR #10/#11: the form must post somewhere that exists, with a real key."""
    html = _read(built_site, "contact/index.html")
    assert "formspree" not in html.lower(), "dead Formspree endpoint is back in the contact form"

    key = _site_params().get("web3forms_key") or ""
    if key:
        assert "api.web3forms.com/submit" in html, (
            "web3forms_key is set but the form does not post to Web3Forms"
        )
        assert re.search(
            r'name=["\']?access_key["\']?\s+value=["\']?' + re.escape(key), html
        ), "Web3Forms access_key is not rendered into the form — email delivery is dead"
    else:
        assert "mailto:" in html, (
            "no web3forms_key configured, so the form must fall back to a mailto: link"
        )
    assert "wa.me/" in html, "WhatsApp path (the primary, zero-setup route) is missing"


def test_repair_claim_matches_config(built_site):
    """PR #13: the headline repair figure must come from config, never from the
    number of blog posts.

    The bug was subtle precisely because the old value was *derived* and therefore
    always 'correct' — it just measured the wrong thing. So assert both directions:
    the configured total is shown, and the post count is not.
    """
    params = _site_params()
    total = params.get("repairsTotal")
    assert total, (
        "params.repairsTotal is not set in hugo.yaml — the homepage repair claim would "
        "fall back to a count derived from content/blog (the PR #13 bug)"
    )

    html = _read(built_site, "index.html")
    counts = re.findall(r'data-count=["\']?(\d+)', html)
    assert counts, "homepage stats band emitted no data-count values"
    assert str(total) in counts, (
        f"homepage does not show params.repairsTotal ({total}); data-count values were {counts}"
    )

    n_posts = len(list(CONTENT_BLOG_DIR.rglob("index.md")))
    assert str(n_posts) not in counts, (
        f"homepage is presenting the blog-post count ({n_posts}) as a repair statistic — "
        "that is the number of case studies published, not devices repaired"
    )


def test_internal_refs_resolve(built_site):
    """EVERY internal link and asset, on EVERY built page, must resolve to a file
    Hugo actually emitted.

    Catches the Redmi-4 class of bug: a reference whose case does not match the file
    on disk (fine on macOS, 404 on the Linux Pages server).

    This deliberately scans the whole output rather than a sample. A 25-post sample
    was tried first and it *missed the real bug* — the offending post simply wasn't
    in the sample. Deduplicating refs before resolving keeps it fast: ~1,570 pages
    share a few thousand distinct targets, and each is stat-ed once.
    """
    first_seen = {}
    for page in sorted(built_site.rglob("*.html")):
        html = page.read_text(encoding="utf-8", errors="ignore")
        for ref in _internal_targets(html):
            first_seen.setdefault(ref, page.relative_to(built_site).as_posix())

    assert len(first_seen) >= MIN_EXPECTED_REFS, (
        f"only {len(first_seen)} distinct internal refs extracted (expected "
        f">={MIN_EXPECTED_REFS}) — attribute extraction is broken, so this test would "
        f"pass vacuously rather than actually checking anything"
    )

    broken = []
    for ref, page in first_seen.items():
        target = _resolve(built_site, ref)
        # exists() is case-sensitive on Linux but NOT on macOS, so confirm the real
        # directory entry matches too — otherwise this guard silently weakens on the
        # machine the site is usually developed on.
        ok = target.exists() and target.name in {p.name for p in target.parent.iterdir()}
        if not ok:
            broken.append((page, ref))

    assert not broken, (
        f"{len(broken)} of {len(first_seen)} distinct internal references do not "
        f"resolve in the built site, e.g. {sorted(broken)[:8]}"
    )


def test_no_template_leakage(built_site):
    """Unrendered Go-template syntax, or Hugo's ZgotmplZ marker (emitted when it
    refuses a URL it considers unsafe/malformed), means a silently broken page."""
    for rel in KEY_PAGES:
        html = _read(built_site, rel)
        assert "{{" not in html, f"{rel}: unrendered template syntax in output"
        assert "ZgotmplZ" not in html, f"{rel}: Hugo rejected a URL as unsafe (ZgotmplZ)"


# --- analytics (spec 011) ------------------------------------------------------
ANALYTICS_MARKERS = ("googletagmanager.com", "google-analytics.com", "gtag(", "ga('create'")


def test_no_analytics_until_an_id_is_configured(built_site):
    """Not tracking must be the DEFAULT, not something someone remembers to turn off.

    This is the property that protects visitors today, in every fork, and in every local
    build — and the one that breaks silently if an ID is pasted somewhere unexpected.
    """
    import yaml
    cfg = yaml.safe_load((REPO_ROOT / "hugo.yaml").read_text(encoding="utf-8"))
    configured = (cfg.get("services", {}).get("googleAnalytics", {}) or {}).get("id") or ""
    if configured:
        pytest.skip("an analytics ID is configured; the negative case no longer applies")

    for rel in ("index.html", "contact/index.html"):
        html = _read(built_site, rel)
        for marker in ANALYTICS_MARKERS:
            assert marker not in html, (
                f"{rel} emits {marker!r} with no analytics ID configured — visitors are being "
                f"tracked by something that was never switched on deliberately")


def test_do_not_track_is_respected():
    import yaml
    cfg = yaml.safe_load((REPO_ROOT / "hugo.yaml").read_text(encoding="utf-8"))
    privacy = (cfg.get("privacy", {}).get("googleAnalytics", {}) or {})
    assert privacy.get("respectDoNotTrack") is True, (
        "a visitor's Do Not Track signal must be honoured without the owner configuring "
        "anything (spec 011 FR-003)")


def test_configuring_an_id_actually_emits_the_tag(tmp_path):
    """The positive direction, proven on a real build with the ID injected via the environment
    so no property ID has to be committed. Without this, the negative test above would pass
    just as happily on a site where analytics could never work at all."""
    import os
    import subprocess

    out = tmp_path / "with-ga"
    env = {**os.environ, "HUGO_SERVICES_GOOGLEANALYTICS_ID": "G-TESTONLY123"}
    proc = subprocess.run(
        ["hugo", "--minify", "--destination", str(out), "--logLevel", "warn"],
        cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, f"build failed:\n{proc.stderr}"
    html = (out / "index.html").read_text(encoding="utf-8", errors="ignore")
    assert any(m in html for m in ANALYTICS_MARKERS), (
        "setting an analytics ID produced no tag — the integration is inert, and the "
        "'no tracking by default' test would pass on a permanently broken setup")
