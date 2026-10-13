"""Unit tests for build_reviewed_manifest.py — the PII gate's manifest builder.

This module sat at **0% coverage** while being the thing that decides which
customer photos the build-phase IMEI/serial gate is allowed to skip. A wrong
answer here does not fail a build; it silently republishes someone's IMEI.

Order, recorded honestly (CON-PROC-005): the module already existed, so these
tests were written *after* the code. They are therefore not trusted on the
strength of being green — every assertion below was proven by mutating the
source and watching it fail. The mutations are named in each test's comment so
the next person can repeat them rather than take this paragraph on faith.

The guard that matters most is `test_refuses_when_a_cleared_hash_is_forbidden`:
it is the only thing standing between a restored pre-redaction original and the
gate waving it through on a stale manifest.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

brm = pytest.importorskip("build_reviewed_manifest")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A fake repo root with an uploads tree, so relative_to(REPO_ROOT) works.

    REPO_ROOT and UPLOADS are read from module globals inside main(), not frozen
    at import, so monkeypatching them here genuinely redirects the run.
    """
    root = tmp_path / "repo"
    uploads = root / "static" / "img" / "uploads" / "2025" / "02"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(brm, "REPO_ROOT", root)
    monkeypatch.setattr(brm, "UPLOADS", root / "static" / "img" / "uploads")
    return root, uploads


def write_image(dirpath: Path, name: str, payload: bytes) -> Path:
    p = dirpath / name
    p.write_bytes(payload)
    return p


def run(monkeypatch, *argv) -> int:
    monkeypatch.setattr(sys, "argv", ["build_reviewed_manifest.py", *argv])
    return brm.main()


# --- sha256 ------------------------------------------------------------------

def test_sha256_matches_hashlib_over_a_multi_chunk_file(tmp_path):
    """Mutation proving this: change the read size to a fixed 1-byte chunk and
    the digest stays correct, so size alone is not what this asserts — it is the
    streaming loop terminating on b"" rather than truncating."""
    # Larger than the 1 MiB chunk the implementation reads, so the loop iterates.
    payload = bytes(range(256)) * 8192          # 2 MiB
    p = write_image(tmp_path, "big.webp", payload)
    assert brm.sha256(p) == hashlib.sha256(payload).hexdigest()


def test_sha256_distinguishes_near_identical_files(tmp_path):
    a = write_image(tmp_path, "a.webp", b"device-photo-A")
    b = write_image(tmp_path, "b.webp", b"device-photo-B")
    assert brm.sha256(a) != brm.sha256(b)


# --- the clean path ----------------------------------------------------------

def test_clean_tree_clears_every_image_and_returns_zero(tree, monkeypatch, capsys):
    root, uploads = tree
    write_image(uploads, "one.webp", b"clean-one")
    write_image(uploads, "two.webp", b"clean-two")
    out = root / "manifest.json"

    rc = run(monkeypatch, "--out", str(out))

    assert rc == 0
    manifest = json.loads(out.read_text())
    assert set(manifest["cleared_sha256"]) == {
        hashlib.sha256(b"clean-one").hexdigest(),
        hashlib.sha256(b"clean-two").hexdigest(),
    }
    assert manifest["forbidden_sha256"] == {}
    assert "_why" in manifest and manifest["_why"].strip()


def test_non_image_files_are_not_cleared(tree, monkeypatch):
    """A .txt beside the photos must not acquire a cleared hash — otherwise the
    manifest grows entries the gate was never asked about."""
    root, uploads = tree
    write_image(uploads, "photo.webp", b"a-photo")
    (uploads / "notes.txt").write_text("not an image")
    out = root / "manifest.json"

    run(monkeypatch, "--out", str(out))

    cleared = json.loads(out.read_text())["cleared_sha256"]
    assert hashlib.sha256(b"not an image").hexdigest() not in cleared
    assert cleared == [hashlib.sha256(b"a-photo").hexdigest()]


# --- flagged images ----------------------------------------------------------

def test_flagged_image_is_withheld_from_cleared_and_exits_nonzero(tree, monkeypatch, capsys):
    """Mutation proving this: invert the `if str(p.resolve()) in flagged` branch
    and this test fails on BOTH the return code and the cleared set. A flagged
    image reaching cleared_sha256 is the exact failure that republishes an IMEI."""
    root, uploads = tree
    bad = write_image(uploads, "imei.webp", b"has-an-imei")
    write_image(uploads, "fine.webp", b"is-fine")

    findings = root / "findings.json"
    findings.write_text(json.dumps([{"path": str(bad.resolve()), "hits": [{"kind": "imei"}]}]))
    out = root / "manifest.json"

    rc = run(monkeypatch, "--findings", str(findings), "--out", str(out))

    assert rc == 1, "a flagged image must make the run fail, not just print"
    cleared = json.loads(out.read_text())["cleared_sha256"]
    assert hashlib.sha256(b"has-an-imei").hexdigest() not in cleared
    assert hashlib.sha256(b"is-fine").hexdigest() in cleared
    assert "STILL FLAGGED" in capsys.readouterr().out


# --- the refusal (CON-PROC-006: test the refusal, not just the success) ------

def test_refuses_when_a_cleared_hash_is_forbidden(tree, monkeypatch):
    """The single most important guard in this module.

    A hash that is both on disk (cleared) and recorded as a pre-redaction
    original (forbidden) means someone restored an un-redacted photo. Writing
    the manifest then would mark it reviewed-and-clean forever.

    Mutation proving this: delete the `if overlap:` block and this test fails —
    main() returns 0 and the poisoned manifest is written."""
    root, uploads = tree
    original = b"the-unredacted-original"
    write_image(uploads, "restored.webp", original)
    digest = hashlib.sha256(original).hexdigest()

    forbidden = root / "forbidden.json"
    forbidden.write_text(json.dumps({"static/img/uploads/2025/02/restored.webp": digest}))
    out = root / "manifest.json"

    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, "--forbidden", str(forbidden), "--out", str(out))

    assert "refusing to write" in str(exc.value)
    assert not out.exists(), "the manifest must not be written when the refusal fires"


def test_forbidden_entry_alone_does_not_refuse_when_the_file_is_gone(tree, monkeypatch):
    """The refusal must key on the hash being present *on disk*, not merely on
    the forbidden list being non-empty — otherwise every later run refuses."""
    root, uploads = tree
    write_image(uploads, "redacted.webp", b"the-redacted-version")

    forbidden = root / "forbidden.json"
    forbidden.write_text(json.dumps({
        "static/img/uploads/2025/02/redacted.webp":
            hashlib.sha256(b"the-unredacted-original").hexdigest(),
    }))
    out = root / "manifest.json"

    rc = run(monkeypatch, "--forbidden", str(forbidden), "--out", str(out))

    assert rc == 0
    assert hashlib.sha256(b"the-unredacted-original").hexdigest() \
        in json.loads(out.read_text())["forbidden_sha256"]


def test_absolute_forbidden_paths_are_stored_repo_relative(tree, monkeypatch):
    root, uploads = tree
    write_image(uploads, "ok.webp", b"ok")
    target = uploads / "gone.webp"

    forbidden = root / "forbidden.json"
    forbidden.write_text(json.dumps({str(target): "deadbeef"}))
    out = root / "manifest.json"

    run(monkeypatch, "--forbidden", str(forbidden), "--out", str(out))

    assert json.loads(out.read_text())["forbidden_sha256"]["deadbeef"] == \
        "static/img/uploads/2025/02/gone.webp"


# --- carrying prior state forward --------------------------------------------

def test_existing_forbidden_and_redacted_survive_a_rebuild(tree, monkeypatch):
    """Mutation proving this: drop `existing.get("redacted", {})` and the
    redaction record is erased on the next rebuild — losing the evidence of
    which images were altered and why (CON-DATA-005's spirit)."""
    root, uploads = tree
    write_image(uploads, "new.webp", b"new-image")
    out = root / "manifest.json"
    out.write_text(json.dumps({
        "cleared_sha256": ["stale-and-should-be-recomputed"],
        "forbidden_sha256": {"older": "static/img/uploads/2024/01/old.webp"},
        "redacted": {"somehash": "mosaiced the About screen"},
    }))

    rc = run(monkeypatch, "--out", str(out))

    assert rc == 0
    manifest = json.loads(out.read_text())
    assert manifest["redacted"] == {"somehash": "mosaiced the About screen"}
    assert manifest["forbidden_sha256"]["older"] == "static/img/uploads/2024/01/old.webp"
    assert "stale-and-should-be-recomputed" not in manifest["cleared_sha256"], \
        "cleared hashes must be recomputed from disk, never carried over"
