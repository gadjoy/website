"""Unit tests for scan_device_identifiers.py — the local PII sweep driver.

0% covered before this file. It is the tool that found 229 images publishing
customer serials, IMEIs and MACs, so the behaviour that matters is not the happy
path but the two ways it can quietly under-report:

  * exiting as if clean when tesseract is simply absent, and
  * letting one unreadable image abort the sweep of the remaining thousands.

Order, recorded honestly (CON-PROC-005): written after the module existed. Each
test names the mutation that was applied to prove it can fail; green alone was
not treated as evidence.

The process pool is replaced with a serial stand-in that still hands back real
concurrent.futures.Future objects, so the module's own `as_completed` loop is
the thing under test rather than a mock of it. A real pool would also defeat
monkeypatching, since subprocesses do not inherit the patched scan_image.
"""
import json
import sys
from concurrent.futures import Future
from pathlib import Path

import pytest

scan = pytest.importorskip("scan_device_identifiers")


class SerialExecutor:
    """Runs submitted work immediately, returning a settled real Future."""

    def __init__(self, max_workers=None):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args, **kwargs):
        fut = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except BaseException as exc:                       # mirrors pool semantics
            fut.set_exception(exc)
        return fut


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setattr(scan, "ProcessPoolExecutor", SerialExecutor)


@pytest.fixture
def tesseract_present(monkeypatch):
    monkeypatch.setattr(scan, "have_tesseract", lambda: True)


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["scan_device_identifiers.py", *argv])
    return scan.main()


# --- the refusal (CON-PROC-006) ----------------------------------------------

def test_exits_when_tesseract_is_missing(monkeypatch, tmp_path, pool):
    """Mutation proving this: change `if not have_tesseract()` to `if False` and
    the sweep runs to completion reporting zero findings — a clean bill of health
    produced by never having looked. CON-DATA-001: that is a fabrication, not an
    observation, and it is why this must exit rather than warn."""
    monkeypatch.setattr(scan, "have_tesseract", lambda: False)
    monkeypatch.setattr(scan, "iter_images", lambda root: [])   # see note below

    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, "--out", str(tmp_path / "f.json"))

    assert "tesseract not found" in str(exc.value)


def test_missing_tesseract_writes_no_findings_file(monkeypatch, tmp_path, pool):
    """A findings file written during a failed sweep would later be read as
    'scanned, nothing found'.

    iter_images is neutralised here even though the exit should make it
    unreachable: without that, mutating the tesseract check sends this test into
    a real OCR sweep of the whole uploads tree and it hangs instead of failing.
    A test whose assertion depends on the code under test being unreachable
    cannot demonstrate its own failure.
    """
    out = tmp_path / "findings.json"
    monkeypatch.setattr(scan, "have_tesseract", lambda: False)
    monkeypatch.setattr(scan, "iter_images", lambda root: [])

    with pytest.raises(SystemExit):
        run(monkeypatch, "--out", str(out))

    assert not out.exists()


# --- target selection --------------------------------------------------------

def test_explicit_paths_bypass_the_tree_walk(monkeypatch, tmp_path, pool, tesseract_present):
    walked = []
    monkeypatch.setattr(scan, "iter_images", lambda root: walked.append(root) or [])
    seen = []
    monkeypatch.setattr(scan, "scan_image", lambda p: seen.append(p) or None)
    out = tmp_path / "findings.json"

    run(monkeypatch, "--paths", "a.webp", "b.webp", "--out", str(out))

    assert [p.name for p in seen] == ["a.webp", "b.webp"]
    assert walked == [], "--paths must not also walk the tree"


def test_without_paths_the_tree_is_walked(monkeypatch, tmp_path, pool, tesseract_present):
    images = [tmp_path / "x.webp", tmp_path / "y.webp"]
    monkeypatch.setattr(scan, "iter_images", lambda root: iter(images))
    monkeypatch.setattr(scan, "scan_image", lambda p: None)
    out = tmp_path / "findings.json"

    run(monkeypatch, "--root", str(tmp_path), "--out", str(out))

    assert json.loads(out.read_text()) == []


# --- findings ----------------------------------------------------------------

def test_findings_are_written_sorted_by_path(monkeypatch, tmp_path, pool, tesseract_present):
    """Mutation proving this: delete the `findings.sort(...)` line and the order
    follows completion order instead, making the JSON churn between runs and
    every diff unreadable."""
    hits = {
        "/z/third.webp": {"path": "/z/third.webp", "hits": [{"kind": "imei"}]},
        "/a/first.webp": {"path": "/a/first.webp", "hits": [{"kind": "mac"}]},
        "/m/second.webp": {"path": "/m/second.webp", "hits": [{"kind": "serial"}]},
    }
    monkeypatch.setattr(scan, "iter_images", lambda root: [Path(p) for p in hits])
    monkeypatch.setattr(scan, "scan_image", lambda p: hits[str(p)])
    out = tmp_path / "findings.json"

    run(monkeypatch, "--root", str(tmp_path), "--out", str(out))

    written = json.loads(out.read_text())
    assert [f["path"] for f in written] == ["/a/first.webp", "/m/second.webp", "/z/third.webp"]


def test_clean_images_produce_no_findings(monkeypatch, tmp_path, pool, tesseract_present):
    """scan_image returns a falsy value for a clean image; those must not be
    recorded, or every image would read as flagged."""
    monkeypatch.setattr(scan, "iter_images", lambda root: [Path("/a.webp"), Path("/b.webp")])
    monkeypatch.setattr(scan, "scan_image", lambda p: None)
    out = tmp_path / "findings.json"

    run(monkeypatch, "--root", str(tmp_path), "--out", str(out))

    assert json.loads(out.read_text()) == []


# --- resilience --------------------------------------------------------------

def test_one_unreadable_image_does_not_abort_the_sweep(monkeypatch, tmp_path, pool,
                                                       tesseract_present, capsys):
    """Mutation proving this: remove the try/except around `fut.result()` and the
    run dies on the corrupt file, losing every finding after it. The sweep covers
    thousands of images; aborting partway reports fewer findings than exist,
    which is the dangerous direction."""
    def fake_scan(p):
        if p.name == "corrupt.webp":
            raise OSError("cannot identify image file")
        return {"path": str(p), "hits": [{"kind": "imei"}]}

    monkeypatch.setattr(scan, "iter_images", lambda root: [
        Path("/a/corrupt.webp"), Path("/b/good.webp"),
    ])
    monkeypatch.setattr(scan, "scan_image", fake_scan)
    out = tmp_path / "findings.json"

    run(monkeypatch, "--root", str(tmp_path), "--out", str(out))

    written = json.loads(out.read_text())
    assert [f["path"] for f in written] == ["/b/good.webp"], \
        "the readable image's finding must survive its neighbour's failure"
    assert "cannot identify image file" in capsys.readouterr().out, \
        "a skipped image must be reported, not swallowed (CON-DATA-001)"


def test_the_failing_image_is_named_in_the_output(monkeypatch, tmp_path, pool,
                                                  tesseract_present, capsys):
    """'could not scan' without saying which file sends the reader nowhere
    (CON-VER-005)."""
    monkeypatch.setattr(scan, "iter_images", lambda root: [Path("/x/broken.webp")])
    monkeypatch.setattr(scan, "scan_image", lambda p: (_ for _ in ()).throw(OSError("boom")))
    out = tmp_path / "findings.json"

    run(monkeypatch, "--root", str(tmp_path), "--out", str(out))

    assert "broken.webp" in capsys.readouterr().out
