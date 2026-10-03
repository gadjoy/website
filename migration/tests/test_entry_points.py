"""Every entry point still runs, and every --dry-run really is dry.

Spec 012, FR-006/FR-007 (SC-006, SC-007).

A script that stopped being runnable is found by the next person at the moment
they need it. These checks move that to CI.

READ THIS BEFORE ADDING A SCRIPT TO THE LIST
--------------------------------------------
HELPABLE is an explicit allow-list, never a glob over the directory, because
most scripts here CANNOT safely be invoked. Fourteen of the twenty-five entry
points in tools/ and migration/scripts/ have an `if __name__ == "__main__"`
guard and **no argument parsing at all**: they ignore argv and begin working
immediately. `python migration/scripts/fix_image_paths.py --help` does not
print help — it opens every markdown file under content/blog for writing.

So a glob-driven version of this test would, on its first run, rewrite the
site's authoritative content. The allow-list is the guard (CON-PROC-006: guard
destructive actions by construction, not by remembering).
"""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

PY = sys.executable

# Entry points that parse arguments, and are therefore safe to invoke with --help.
HELPABLE = [
    "tools/deploy_freshness.py",
    "tools/merge_guard.py",
    "tools/publish_decks.py",
    "migration/scripts/build_reviewed_manifest.py",
    "migration/scripts/redact_device_identifiers.py",
    "migration/scripts/scan_device_identifiers.py",
    "migration/scripts/wp_rest_to_hugo.py",
]

# Deliberately NOT invoked, each with its reason. Nothing is omitted silently.
NOT_INVOKED = {
    "tools/check_hygiene.py":
        "vendored from the constitution repo; tested at its source, and its CLI is "
        "exercised by test_compensating_controls.py",
    "tools/deck_to_posts.py": "library module, no __main__ guard",
    "migration/scripts/device_identifiers.py": "library module, no __main__ guard",
    "migration/scripts/optimize_media.py":
        "no argument parsing — invoking it prunes and re-encodes the uploads tree",
    "migration/scripts/wp_to_hugo.py":
        "recorded in specs/001 plan.md as 'OLD - broken; left for reference, not run'; "
        "not valid Python",
}
# The one-shot migration scripts: __main__ guard, no argparse, immediate writes.
NO_ARGPARSE_ONE_SHOT = [
    "check_missing_images.py", "cleanup_blog_content.py", "cleanup_content.py",
    "comprehensive_frontmatter_fix.py", "comprehensive_image_audit.py",
    "final_blog_cleanup.py", "final_cleanup.py", "fix_frontmatter.py",
    "fix_image_paths.py", "fix_image_placeholders.py", "fix_missing_images.py",
    "quick_image_check.py", "universal_theme_optimization.py",
]


@pytest.mark.parametrize("rel", HELPABLE)
def test_every_entry_point_answers_help(rel):
    """Mutation proving this: break an import in any listed script and it fails."""
    out = subprocess.run([PY, str(REPO_ROOT / rel), "--help"],
                         capture_output=True, text=True, timeout=60, cwd=REPO_ROOT)

    assert out.returncode == 0, f"{rel} --help exited {out.returncode}:\n{out.stderr[-800:]}"
    assert "usage" in out.stdout.lower(), f"{rel} --help printed no usage line"


def test_the_allow_list_still_matches_what_is_on_disk():
    """A new script must be classified deliberately, not quietly skipped.

    Mutation proving this: add a file to tools/ and this fails until it is
    either allow-listed or given a documented reason not to be.
    """
    on_disk = {
        f"{d}/{p.name}"
        for d in ("tools", "migration/scripts")
        for p in (REPO_ROOT / d).glob("*.py")
    }
    classified = set(HELPABLE) | set(NOT_INVOKED) | {
        f"migration/scripts/{n}" for n in NO_ARGPARSE_ONE_SHOT}

    unclassified = on_disk - classified
    assert not unclassified, (
        f"unclassified entry points: {sorted(unclassified)}. Add each to HELPABLE if it "
        f"parses arguments, or to NOT_INVOKED/NO_ARGPARSE_ONE_SHOT with a reason. Do not "
        f"widen this test into a glob — most scripts here execute on invocation."
    )


@pytest.mark.parametrize("name", NO_ARGPARSE_ONE_SHOT)
def test_one_shot_scripts_are_still_argument_blind(name):
    """CHARACTERIZATION TEST — records a real hazard, statically.

    These scripts take no arguments and act on import-time invocation, so
    `--help` runs them. This asserts the hazard still exists by READING the
    source; it never executes them. If one grows an ArgumentParser, this fails
    and it should move to HELPABLE.
    """
    src = (REPO_ROOT / "migration" / "scripts" / name).read_text(encoding="utf-8")

    assert "ArgumentParser" not in src, (
        f"{name} now parses arguments — move it to HELPABLE and delete this entry"
    )


# --- --dry-run really is dry -------------------------------------------------

def tree_digest(root: Path) -> str:
    """Hash file CONTENTS, not mtimes — an mtime-based digest would pass for the
    wrong reason on a rewrite that produced identical bytes, and fail spuriously
    on a touch."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


DECK = REPO_ROOT / "migration/wp-export/wp-content/uploads/2022/02/Repair-1.1.7.pptx"


@pytest.mark.skipif(not DECK.is_file(), reason="deck fixture absent")
def test_publish_decks_dry_run_writes_nothing(tmp_path):
    """The real CLI, as a subprocess, against the real content tree.

    The per-module tests stub publish_deck; this one does not, so it covers the
    path where a dry run would otherwise write post bundles and images into
    content/blog and static/img.
    """
    watched = [REPO_ROOT / "content", REPO_ROOT / "static" / "img" / "uploads"]
    before = [tree_digest(d) for d in watched]

    out = subprocess.run(
        [PY, str(REPO_ROOT / "tools" / "publish_decks.py"),
         "--deck", str(DECK), "--date", "2026-03-09", "--dry-run"],
        capture_output=True, text=True, timeout=300, cwd=REPO_ROOT)

    assert out.returncode == 0, out.stderr[-1500:]
    assert [tree_digest(d) for d in watched] == before, (
        "--dry-run modified the working tree")


def test_redact_dry_run_writes_nothing(tmp_path):
    from PIL import Image
    p = tmp_path / "shot.png"
    Image.new("RGB", (200, 200), (10, 20, 30)).save(p, "PNG")
    before = p.read_bytes()

    out = subprocess.run(
        [PY, str(REPO_ROOT / "migration" / "scripts" / "redact_device_identifiers.py"),
         str(p), "--box", "0,0,50,50", "--dry-run"],
        capture_output=True, text=True, timeout=60, cwd=REPO_ROOT)

    assert out.returncode == 0, out.stderr[-800:]
    assert p.read_bytes() == before


def test_merge_guard_dry_run_does_not_merge(tmp_path):
    """Run with a PR number that cannot exist, so even a broken guard has nothing
    to merge. What is asserted is that --dry-run refuses rather than shelling out."""
    out = subprocess.run(
        [PY, str(REPO_ROOT / "tools" / "merge_guard.py"), "999999", "--dry-run"],
        capture_output=True, text=True, timeout=120, cwd=REPO_ROOT)

    assert out.returncode == 1, "a PR with no checks must be refused"
    assert "REFUSING" in out.stderr
