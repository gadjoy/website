"""Network and orchestration tests for publish_decks.py.

test_deck_intake.py covers the pure routing regexes. Everything that actually
talks to GitHub — the three request builders, publish_from_intake's control flow
and main's argument routing — was untested, which is 81 of this module's 123
statements. This is the unattended path: it runs on a repository_dispatch with a
token, writes posts into the site and comments back on the team's issue, with
nobody watching it happen.

urllib.request.urlopen is stubbed throughout. The assertions are mostly about
the Request objects the module builds, because the defects that bite here are in
headers and URLs, not in response handling — see test_repo_file_asks_for_raw_bytes.

Order, recorded honestly (CON-PROC-005): written after the module existed. Each
guard names the mutation that proves it can fail.
"""
import io
import json
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "migration" / "scripts"))


@pytest.fixture(scope="module")
def pd():
    import publish_decks
    return publish_decks


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def capture(pd, monkeypatch):
    """Record every Request the module builds; serve canned bodies in order."""
    sent, queue = [], []

    def fake_urlopen(req, timeout=None):
        sent.append(req)
        return FakeResponse(queue.pop(0) if queue else b"{}")

    monkeypatch.setattr(pd.urllib.request, "urlopen", fake_urlopen)
    return sent, queue


# --- request builders --------------------------------------------------------

def test_gh_json_authenticates_and_parses(pd, capture):
    sent, queue = capture
    queue.append(json.dumps([{"number": 7}]).encode())

    out = pd._gh_json("https://api.github.com/x", "tok123")

    assert out == [{"number": 7}]
    assert sent[0].get_header("Authorization") == "Bearer tok123"
    assert sent[0].get_header("Accept") == "application/vnd.github+json"


def test_repo_file_asks_for_raw_bytes(pd, capture):
    """Mutation proving this: change the Accept header to
    application/vnd.github+json and the test fails.

    The default JSON response base64-encodes the file and refuses anything over
    1MB. A week's deck is several MB, so this header is the difference between
    the repo route working and failing on every real deck — and it fails with a
    size error that looks like a GitHub problem rather than a header one.
    """
    sent, queue = capture
    queue.append(b"PK\x03\x04deckbytes")

    data = pd._repo_file("gadjoy/repairs-intake", "decks/w42.pptx", "tok")

    assert data == b"PK\x03\x04deckbytes"
    assert sent[0].get_header("Accept") == "application/vnd.github.raw"
    assert sent[0].full_url == (
        "https://api.github.com/repos/gadjoy/repairs-intake/contents/decks/w42.pptx")


def test_download_sends_the_token(pd, capture):
    """Issue attachments on a private repo 404 without credentials."""
    sent, queue = capture
    queue.append(b"bytes")

    assert pd._download("https://github.com/user-attachments/files/1/a.pptx", "tok") == b"bytes"
    assert sent[0].get_header("Authorization") == "Bearer tok"


def test_comment_posts_the_body(pd, capture):
    sent, _ = capture

    pd._comment("o/r", 12, "published!", "tok")

    assert sent[0].get_method() == "POST"
    assert sent[0].full_url == "https://api.github.com/repos/o/r/issues/12/comments"
    assert json.loads(sent[0].data) == {"body": "published!"}


def test_close_patches_state_closed(pd, capture):
    """Mutation proving this: change the method to POST and GitHub creates
    nothing but silently leaves the issue open — the team then re-files it."""
    sent, _ = capture

    pd._close("o/r", 12, "tok")

    assert sent[0].get_method() == "PATCH"
    assert json.loads(sent[0].data) == {"state": "closed"}


# --- collect_decks ordering --------------------------------------------------

def test_repo_route_is_tried_before_attachments(pd, monkeypatch):
    """The repo route works at any size; the attachment route is capped at 25MB.
    Order is the contract, so it is asserted rather than assumed."""
    monkeypatch.setattr(pd, "_repo_file", lambda intake, path, token: b"repo")
    monkeypatch.setattr(pd, "_download", lambda url, token: b"attach")
    body = ("see decks/week-42.pptx and "
            "https://github.com/user-attachments/files/9/extra.pptx")

    got = list(pd.collect_decks("o/r", body, "tok"))

    assert [n for n, _ in got] == ["week-42.pptx", "extra.pptx"]
    assert [d for _, d in got] == [b"repo", b"attach"]


def test_a_deck_named_twice_is_fetched_once(pd, monkeypatch):
    calls = []
    monkeypatch.setattr(pd, "_repo_file",
                        lambda intake, path, token: calls.append(path) or b"x")
    body = "decks/w1.pptx and again decks/w1.pptx"

    list(pd.collect_decks("o/r", body, "tok"))

    assert calls == ["decks/w1.pptx"]


# --- publish_from_intake: the refusal ---------------------------------------

def test_missing_token_exits_rather_than_running(pd, monkeypatch):
    """Mutation proving this: replace sys.exit with a warning and the run
    proceeds to an unauthenticated API call, which on a private repo returns 404
    and reads as 'no open deck issues' — a silent no-op that looks like success.
    """
    monkeypatch.delenv("INTAKE_TOKEN", raising=False)
    # Neutralised even though the exit should make it unreachable: without this,
    # mutating the exit away sends the test to the real api.github.com and it
    # fails with an HTTPError instead of on its own assertion. Same lesson as
    # the tesseract tests in test_scan_device_identifiers.py — a test must be
    # able to fail offline and fast.
    monkeypatch.setattr(pd, "_gh_json", lambda url, token: [])

    with pytest.raises(SystemExit) as exc:
        pd.publish_from_intake("o/r", dry_run=False)

    assert "INTAKE_TOKEN" in str(exc.value)


# --- publish_from_intake: control flow --------------------------------------

@pytest.fixture
def intake(pd, monkeypatch):
    """INTAKE_TOKEN set, and _gh_json serving a scripted issue list."""
    monkeypatch.setenv("INTAKE_TOKEN", "tok")

    def serve(issues):
        monkeypatch.setattr(pd, "_gh_json", lambda url, token: issues)
    return serve


def test_no_open_issues_is_success_not_failure(pd, intake, capsys):
    intake([])

    assert pd.publish_from_intake("o/r", dry_run=False) == 0
    assert "no open deck issues" in capsys.readouterr().out


def test_an_issue_without_a_date_is_reported_as_a_failure(pd, intake, monkeypatch, capsys):
    """RUN_DATE is the fallback; with neither, publishing would date the post
    from the slide, which the deck format treats as a stale placeholder."""
    intake([{"number": 5, "body": "no date here"}])
    monkeypatch.delenv("RUN_DATE", raising=False)

    rc = pd.publish_from_intake("o/r", dry_run=False)

    assert rc == 1
    assert "no week-ending date" in capsys.readouterr().out


def test_run_date_is_the_fallback_when_the_body_omits_one(pd, intake, monkeypatch, capsys):
    intake([{"number": 5, "body": "deck: decks/a.pptx"}])
    monkeypatch.setenv("RUN_DATE", "2026-03-09T00:00:00Z")
    monkeypatch.setattr(pd, "collect_decks", lambda i, b, t: [])

    pd.publish_from_intake("o/r", dry_run=False)

    # The deck is missing, but the date was accepted — the failure names the deck.
    assert "no deck found" in capsys.readouterr().out


def test_an_issue_with_no_deck_is_reported_as_a_failure(pd, intake, capsys):
    intake([{"number": 5, "body": "week ending 2026-03-09, forgot the file"}])

    rc = pd.publish_from_intake("o/r", dry_run=False)
    out = capsys.readouterr().out

    assert rc == 1
    assert "no deck found" in out
    assert "decks/" in out, "the failure must say how to supply the deck"


def test_a_malformed_deck_fails_that_issue_without_stopping_the_rest(
        pd, intake, monkeypatch, tmp_path, capsys):
    """Mutation proving this: remove the `continue` after the DeckFormatError
    handler and the broken deck's empty report is appended as if it published.

    One team member's malformed deck must not block everyone else's week."""
    intake([
        {"number": 1, "body": "2026-03-09 decks/bad.pptx"},
        {"number": 2, "body": "2026-03-09 decks/good.pptx"},
    ])
    monkeypatch.setattr(pd, "collect_decks",
                        lambda i, body, t: [("bad.pptx", b"x")] if "bad" in body
                        else [("good.pptx", b"x")])

    def fake_publish(deck, **kw):
        if deck.name == "bad.pptx":
            raise pd.DeckFormatError("slide 3 has 3 pictures, expected 2")
        return {"posts": [], "skipped": [], "redactions": []}

    monkeypatch.setattr(pd, "publish_deck", fake_publish)
    monkeypatch.setattr(pd, "report_lines", lambda name, r: [f"published {name}"])

    rc = pd.publish_from_intake("o/r", dry_run=False)
    out = capsys.readouterr().out

    assert rc == 1, "a malformed deck must make the overall run fail"
    assert "published good.pptx" in out, "the healthy issue must still publish"
    assert "slide 3 has 3 pictures" in out, "the reason must reach the operator"


# --- notify ------------------------------------------------------------------

@pytest.fixture
def one_good_issue(pd, intake, monkeypatch):
    intake([{"number": 42, "body": "2026-03-09 decks/w.pptx"}])
    monkeypatch.setattr(pd, "collect_decks", lambda i, b, t: [("w.pptx", b"x")])
    monkeypatch.setattr(pd, "publish_deck",
                        lambda deck, **kw: {"posts": [], "skipped": [], "redactions": []})
    monkeypatch.setattr(pd, "report_lines", lambda name, r: ["- one post"])
    calls = {"comment": [], "close": []}
    monkeypatch.setattr(pd, "_comment",
                        lambda i, n, b, t: calls["comment"].append((n, b)))
    monkeypatch.setattr(pd, "_close", lambda i, n, t: calls["close"].append(n))
    return calls


def test_notify_comments_and_closes_the_issue(pd, one_good_issue):
    pd.publish_from_intake("o/r", dry_run=False, notify=True)

    assert one_good_issue["close"] == [42]
    (num, body), = one_good_issue["comment"]
    assert num == 42
    assert "- one post" in body


def test_dry_run_never_comments_or_closes(pd, one_good_issue):
    """Mutation proving this: drop `and not dry_run` from the notify guard and a
    rehearsal posts to the team's real issue and closes it. --dry-run exists to
    be safe to run against production intake."""
    pd.publish_from_intake("o/r", dry_run=True, notify=True)

    assert one_good_issue["comment"] == []
    assert one_good_issue["close"] == []


def test_notify_off_means_no_api_writes(pd, one_good_issue):
    pd.publish_from_intake("o/r", dry_run=False, notify=False)

    assert one_good_issue["comment"] == []
    assert one_good_issue["close"] == []


def test_a_failure_anywhere_keeps_every_issue_open(pd, intake, monkeypatch):
    """Documents a SHARED-DENOMINATOR behaviour, deliberately.

    `if not failures` is checked inside the per-issue loop but reads the global
    failure list, so one unrelated bad issue leaves even successfully published
    issues open (they are still commented on). That is the safe direction — an
    issue left open is noticed, an issue wrongly closed is not — but it is
    accidental rather than designed, and the constitution calls out exactly this
    shape (CON-PROC-009, the trailward guard whose shared denominator let one
    unrelated failure excuse a total wipe). Pinned so a change here is visible.
    """
    intake([
        {"number": 1, "body": "2026-03-09 decks/good.pptx"},
        {"number": 2, "body": "no date at all"},
    ])
    monkeypatch.setattr(pd, "collect_decks", lambda i, b, t: [("good.pptx", b"x")])
    monkeypatch.setattr(pd, "publish_deck",
                        lambda deck, **kw: {"posts": [], "skipped": [], "redactions": []})
    monkeypatch.setattr(pd, "report_lines", lambda name, r: ["- ok"])
    closed, commented = [], []
    monkeypatch.setattr(pd, "_comment", lambda i, n, b, t: commented.append(n))
    monkeypatch.setattr(pd, "_close", lambda i, n, t: closed.append(n))

    rc = pd.publish_from_intake("o/r", dry_run=False, notify=True)

    assert rc == 1
    assert commented == [1], "the healthy issue is still told what happened"
    assert closed == [], "but nothing is closed while any issue failed"


# --- main --------------------------------------------------------------------

def test_deck_without_date_is_refused(pd, monkeypatch):
    """The slide's own date is a stale placeholder, so --date is mandatory."""
    monkeypatch.setattr(sys, "argv", ["publish_decks.py", "--deck", "x.pptx"])

    with pytest.raises(SystemExit) as exc:
        pd.main()

    assert "--date is required" in str(exc.value)


def test_main_routes_deck_to_publish_local(pd, monkeypatch):
    seen = {}
    monkeypatch.setattr(pd, "publish_local",
                        lambda deck, date, issue, dry: seen.update(
                            deck=deck, date=date, issue=issue, dry=dry) or 0)
    monkeypatch.setattr(sys, "argv", [
        "publish_decks.py", "--deck", "a.pptx", "--date", "2026-03-09",
        "--issue", "7", "--dry-run"])

    assert pd.main() == 0
    assert seen == {"deck": Path("a.pptx"), "date": "2026-03-09", "issue": 7, "dry": True}


def test_main_routes_from_intake(pd, monkeypatch):
    seen = {}
    monkeypatch.setattr(pd, "publish_from_intake",
                        lambda intake, dry, notify: seen.update(
                            intake=intake, dry=dry, notify=notify) or 0)
    monkeypatch.setattr(sys, "argv", [
        "publish_decks.py", "--from-intake", "o/r", "--notify"])

    assert pd.main() == 0
    assert seen == {"intake": "o/r", "dry": False, "notify": True}


def test_main_requires_one_of_the_two_modes(pd, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["publish_decks.py"])

    with pytest.raises(SystemExit):
        pd.main()


def test_publish_local_prints_its_report(pd, monkeypatch, capsys):
    monkeypatch.setattr(pd, "publish_deck",
                        lambda deck, **kw: {"posts": [], "skipped": [], "redactions": []})
    monkeypatch.setattr(pd, "report_lines", lambda name, r: [f"report for {name}"])

    assert pd.publish_local(Path("/tmp/a.pptx"), "2026-03-09", 0, False) == 0
    assert "report for a.pptx" in capsys.readouterr().out
