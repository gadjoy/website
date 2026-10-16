"""SECURITY.md is asserted against reality (spec 012, FR-010/FR-012, SC-010/SC-011).

CON-SEC-004's named failure is not the absence of headers — it is nobody being
able to tell whether that absence was a decision or an oversight. So the
document must exist, must state the GitHub Pages constraint, and must not drift
away from what the site actually returns.

The gitleaks tests here are the ones that matter most. gitleaks 8.21.2 with
STOCK rules reports "no leaks found" against this repo's own former `.env`,
which held a live-format `sk-` OpenAI key and two database passwords. A gate
installed with defaults would have been green while a real credential sat in
HEAD. These tests pin the custom rules that close that, by running the scanner
against a synthetic fixture rather than trusting the config to be correct.

No real secret is used as a fixture. The values below are invented and match
only the SHAPE of a credential.
"""
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from conftest import REPO_ROOT

SECURITY_MD = REPO_ROOT / "SECURITY.md"
GITLEAKS_CFG = REPO_ROOT / ".gitleaks.toml"
needs_gitleaks = pytest.mark.skipif(
    shutil.which("gitleaks") is None, reason="gitleaks not installed")


def scan(tmp_path, files: dict):
    """Run gitleaks with THIS repo's config over a synthetic tree."""
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    cfg = tmp_path / ".gitleaks.toml"
    cfg.write_text(GITLEAKS_CFG.read_text())
    report = tmp_path.parent / f"{tmp_path.name}-report.json"

    proc = subprocess.run(
        ["gitleaks", "detect", "--source", str(tmp_path), "--no-git",
         "--config", str(cfg), "--no-banner", "--report-path", str(report)],
        capture_output=True, text=True, timeout=180)
    findings = json.loads(report.read_text()) if report.is_file() else []
    report.unlink(missing_ok=True)
    return proc.returncode, {f["RuleID"] for f in findings}


# --- the document ------------------------------------------------------------

def test_security_md_exists():
    assert SECURITY_MD.is_file(), "CON-SEC-004 requires a stated security posture"


def test_the_pages_header_constraint_is_recorded():
    """The platform cannot set headers. Saying nothing is the failure the rule
    names, so the document must say it explicitly."""
    body = SECURITY_MD.read_text()

    assert "cannot set response headers" in body
    for header in ("Content-Security-Policy", "Referrer-Policy",
                   "X-Content-Type-Options"):
        assert header in body, f"{header} is not addressed in SECURITY.md"


def test_the_shipped_and_build_trees_are_reported_separately():
    """CON-SEC-003: one combined number misleads, and a build-tree advisory must
    not be dismissed as 'not shipped'."""
    body = SECURITY_MD.read_text()

    assert "Shipped tree" in body and "Build tree" in body


def test_the_credential_finding_is_still_recorded_with_its_disposition():
    """The finding may leave SECURITY.md only by being RESOLVED and SAID SO —
    never by being tidied away.

    It was closed on 2026-10-16 by the owner's assessment that the key is no
    longer active. That is a DECISION, not a verification, and the document has
    to keep saying so: the key was not rotated and the history was not purged,
    so the values are still readable. A record that quietly became "no known
    issues" would misrepresent what happened (CON-DATA-001).

    If you are here because this test failed, the section was edited or removed.
    Restore the disposition, or — if the key really was rotated and the history
    purged — say that instead, with the date.
    """
    body = SECURITY_MD.read_text()

    assert "OPENAI_API_KEY" in body, "the credential finding was removed from SECURITY.md"
    assert "sixteen months" in body, (
        "the exposure window is no longer stated; it is the part that says how "
        "bad this was, and it should not be softened away")
    assert "no rotation performed" in body.lower() or "rotate the openai key" in body.lower(), (
        "SECURITY.md no longer states what was actually done about the key. It "
        "must say either that rotation is outstanding, or that it was "
        "deliberately skipped and why.")


def test_platform_scanning_is_recorded_as_a_gate():
    """It is free, it caught what gitleaks' stock rules missed, and it is now on.
    Recorded so a future reader knows two independent scanners are expected."""
    body = SECURITY_MD.read_text()

    assert "GitHub secret scanning" in body
    assert "push protection" in body.lower()


def test_env_is_not_tracked_by_git():
    """The actual fix, asserted. Mutation proving this: `git add -f .env` and it
    fails. .gitignore alone does NOT untrack an already-tracked file — that is
    precisely how this went unnoticed."""
    out = subprocess.run(["git", "ls-files", "--", ".env"],
                         capture_output=True, text=True, cwd=REPO_ROOT)

    assert out.stdout.strip() == "", (
        ".env is tracked by git. It is gitignored, but gitignore does not untrack "
        "an existing file — run `git rm --cached .env`.")


# --- the scanner actually scans (FR-010, and CON-VER-005) --------------------

@needs_gitleaks
def test_a_project_scoped_openai_key_is_caught(tmp_path):
    """THE regression test for this whole file. A stock gitleaks misses this.

    Mutation proving it: delete the `openai-key-broad` rule from .gitleaks.toml
    and this goes green — which is exactly the state the repo was in.
    """
    rc, rules = scan(tmp_path, {
        ".env": 'OPENAI_API_KEY=sk-proj-' + "A1b2C3d4_e5F6-g7H8" * 7 + "\n"})

    assert rc == 1, "a project-scoped OpenAI key must fail the scan"
    assert "openai-key-broad" in rules


@needs_gitleaks
def test_a_low_entropy_password_in_dotenv_is_caught(tmp_path):
    """`wp_secret123` clears no entropy threshold but is still a credential. In a
    .env file an assignment to *PASSWORD is one by construction."""
    rc, rules = scan(tmp_path, {
        ".env": "MYSQL_ROOT_PASSWORD=rootpass123\nWP_DB_PASSWORD=wp_secret99\n"})

    assert rc == 1
    assert "dotenv-assigned-secret" in rules


@needs_gitleaks
def test_the_scan_is_not_vacuous_on_a_clean_tree(tmp_path):
    """The other direction. A config that flags everything is as useless as one
    that flags nothing, and a gate that cannot pass gets disabled."""
    rc, rules = scan(tmp_path, {
        "hugo.yaml": "params:\n  title: Gadjoy\n",
        "content/post.md": "---\ntitle: A repair\n---\nBody.\n"})

    assert rc == 0, f"clean tree should pass, got {rules}"


@needs_gitleaks
def test_the_public_web3forms_key_is_allowlisted(tmp_path):
    """Public by construction — rendered into every contact page as a hidden
    input, so it is already in the HTML source of the live site. Allowlisted by
    LINE, not by file, so the rest of hugo.yaml is still scanned."""
    rc, _ = scan(tmp_path, {
        "hugo.yaml": 'params:\n  web3forms_key: "440f8a1c-2b3d-4e5f-9a8b-7c6d5e4f3a2b"\n'})

    assert rc == 0


@needs_gitleaks
def test_the_allowlist_does_not_cover_the_whole_config_file(tmp_path):
    """Mutation proving this: widen the allowlist from a line regex to the path
    `hugo.yaml` and this goes green, hiding any future real key in that file."""
    rc, rules = scan(tmp_path, {
        "hugo.yaml": ('params:\n  web3forms_key: "440f8a1c-2b3d-4e5f-9a8b-7c6d5e4f3a2b"\n'
                      '  openai: "sk-proj-' + "A1b2C3d4_e5F6-g7H8" * 7 + '"\n')})

    # Asserting the rule, not just rc. gitleaks exits 1 for a BROKEN CONFIG too,
    # so a return-code-only assertion passes when the config fails to load —
    # which it did during the mutation run that found this.
    assert rc == 1, "a real key elsewhere in hugo.yaml must still be caught"
    assert "openai-key-broad" in rules, (
        f"expected the key to be detected, got {rules or 'no findings (config error?)'}")


@needs_gitleaks
def test_vendored_theme_and_wp_export_are_allowlisted_by_path(tmp_path):
    """Third-party code this repo vendors but does not own."""
    secret = "sk-proj-" + "A1b2C3d4_e5F6-g7H8" * 7
    rc, _ = scan(tmp_path, {
        "themes/hugo-universal-theme/exampleSite/hugo.toml": f'key = "{secret}"\n',
        "migration/wp-export/wp-content/plugins/x/provider.php": f"<?php $k = '{secret}';\n"})

    assert rc == 0


@needs_gitleaks
def test_a_secret_outside_the_vendored_paths_is_still_caught(tmp_path):
    """The path allowlist is broad; this proves it is not unbounded."""
    secret = "sk-proj-" + "A1b2C3d4_e5F6-g7H8" * 7
    rc, _ = scan(tmp_path, {"tools/helper.py": f'KEY = "{secret}"\n'})

    assert rc == 1


# --- the Dependabot trace must stay true (CON-SEC-003) -----------------------

def test_no_node_manifest_at_the_repo_root():
    """SECURITY.md traces 70 Dependabot alerts to vendored WordPress themes that
    are never installed, and that trace rests on CI's `npm ci` step being a
    guarded no-op. Adding a root package.json would silently make the claim
    false and start installing packages in CI.

    Mutation proving this: create package.json at the root and it fails.
    """
    for name in ("package.json", "package-lock.json", "npm-shrinkwrap.json"):
        assert not (REPO_ROOT / name).exists(), (
            f"{name} appeared at the repo root. CI's npm step is no longer a "
            f"no-op, and SECURITY.md's Dependabot trace needs rewriting.")


def test_the_site_does_not_reference_the_vendored_wordpress_themes():
    """The other half of the trace: those themes are unreferenced, so their
    lockfiles are in neither the shipped nor the build tree."""
    import re
    pattern = re.compile(r"twenty(nineteen|twenty|twentyone)", re.I)
    offenders = []
    for d in ("layouts", "static", "data"):
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.suffix.lower() in {".html", ".css", ".js", ".json", ".yaml", ".yml"}:
                try:
                    if pattern.search(f.read_text(encoding="utf-8", errors="ignore")):
                        offenders.append(str(f.relative_to(REPO_ROOT)))
                except OSError:
                    continue
    assert not offenders, (
        f"the site now references vendored WordPress themes: {offenders}. "
        f"SECURITY.md claims they are unreferenced and therefore inert.")
