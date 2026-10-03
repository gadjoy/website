"""CLI and subprocess layers of merge_guard.py and deploy_freshness.py.

test_compensating_controls.py covers the pure decision functions — decide_merge
and assess_freshness — which is the part that was easy to test. What was left
uncovered is everything between those functions and the outside world:
fetch_checks' handling of gh's output, the --wait polling loop, and whether
main() actually refuses rather than merging anyway.

That gap matters because the guard's whole purpose is to stop a merge, and a
correct decision that main() then ignores is worth nothing. PRs #19 and #21 were
both merged with checks still running; this is the code that exists so that
cannot recur.

Order, recorded honestly (CON-PROC-005): written after the modules existed.
Guards proven by mutation; each names its own.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "tools"))


@pytest.fixture(scope="module")
def mg():
    import merge_guard
    return merge_guard


@pytest.fixture(scope="module")
def df():
    import deploy_freshness
    return deploy_freshness


class Done:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


# --- merge_guard.fetch_checks -----------------------------------------------

def test_fetch_checks_parses_gh_output(mg, monkeypatch):
    monkeypatch.setattr(mg.subprocess, "run",
                        lambda *a, **k: Done(json.dumps([{"name": "Test", "state": "SUCCESS"}])))
    assert mg.fetch_checks(21) == [{"name": "Test", "state": "SUCCESS"}]


def test_fetch_checks_survives_gh_exiting_nonzero_on_a_failing_check(mg, monkeypatch):
    """gh exits non-zero when any check is failing. That is data, not an error:
    the guard must still see the FAILURE and refuse, rather than treating the
    exit code as 'could not determine' and falling through."""
    monkeypatch.setattr(mg.subprocess, "run", lambda *a, **k: Done(
        json.dumps([{"name": "Test", "state": "FAILURE"}]), returncode=1))

    checks = mg.fetch_checks(21)

    assert checks == [{"name": "Test", "state": "FAILURE"}]
    assert mg.decide_merge(checks).ok is False


@pytest.mark.parametrize("stdout", ["", "   \n", "not json at all", "{bad"])
def test_unreadable_gh_output_yields_no_checks_which_refuses(mg, monkeypatch, stdout):
    """Mutation proving this: make the JSONDecodeError handler re-raise and the
    guard crashes instead of refusing. Either way it must not MERGE — an
    unreadable answer is 'no checks', and decide_merge refuses on that."""
    monkeypatch.setattr(mg.subprocess, "run", lambda *a, **k: Done(stdout))

    assert mg.fetch_checks(21) == []
    assert mg.decide_merge(mg.fetch_checks(21)).ok is False


# --- merge_guard.main --------------------------------------------------------

@pytest.fixture
def no_merge(mg, monkeypatch):
    """Record any `gh pr merge` the guard attempts."""
    attempts = []

    def fake_run(args, *a, **k):
        if args[:3] == ["gh", "pr", "merge"]:
            attempts.append(args)
            return Done(returncode=0)
        return Done("[]")

    monkeypatch.setattr(mg.subprocess, "run", fake_run)
    return attempts


def test_main_refuses_and_does_not_merge_when_checks_are_red(mg, monkeypatch, no_merge, capsys):
    """Mutation proving this: change `if not verdict.ok` to `if False` and the
    merge goes ahead on a red PR — exactly the #19/#21 incident."""
    monkeypatch.setattr(mg, "fetch_checks",
                        lambda pr: [{"name": "Test", "state": "FAILURE"}])
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21"])

    rc = mg.main()

    assert rc == 1
    assert no_merge == [], "a refused merge must not shell out to gh pr merge"
    assert "REFUSING to merge #21" in capsys.readouterr().err


def test_main_merges_when_every_check_is_green(mg, monkeypatch, no_merge):
    monkeypatch.setattr(mg, "fetch_checks",
                        lambda pr: [{"name": "Test", "state": "SUCCESS"}])
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21"])

    assert mg.main() == 0
    assert no_merge == [["gh", "pr", "merge", "21", "--merge"]]


def test_dry_run_decides_without_merging(mg, monkeypatch, no_merge, capsys):
    monkeypatch.setattr(mg, "fetch_checks",
                        lambda pr: [{"name": "Test", "state": "SUCCESS"}])
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21", "--dry-run"])

    assert mg.main() == 0
    assert no_merge == [], "--dry-run must never merge"
    assert "1 check(s) green" in capsys.readouterr().out


def test_merge_method_is_passed_through(mg, monkeypatch, no_merge):
    """Note the `=` form. The space-separated form does NOT work — see
    test_merge_method_cannot_be_passed_space_separated below."""
    monkeypatch.setattr(mg, "fetch_checks",
                        lambda pr: [{"name": "Test", "state": "SUCCESS"}])
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21", "--merge-method=--squash"])

    mg.main()

    assert no_merge == [["gh", "pr", "merge", "21", "--squash"]]


def test_merge_method_cannot_be_passed_space_separated(mg, monkeypatch):
    """CHARACTERIZATION TEST — a latent CLI defect, recorded not fixed.

    The choices are themselves "--merge"/"--squash"/"--rebase", so argparse reads
    the value as another option and errors with "expected one argument". Only
    `--merge-method=--squash` works, which nothing documents.

    It has never bitten because `make merge` does not pass the flag, so the
    default "--merge" is always used. The fix is to store the choices bare
    ("merge"/"squash"/"rebase") and prepend the dashes when building the gh
    argv — a change to the tool's CLI contract, which does not belong in a
    coverage PR. Pinned here so it is visible and so fixing it is deliberate.
    """
    monkeypatch.setattr(mg, "fetch_checks",
                        lambda pr: [{"name": "Test", "state": "SUCCESS"}])
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21", "--merge-method", "--squash"])

    with pytest.raises(SystemExit) as exc:
        mg.main()

    assert exc.value.code == 2, (
        "if this now parses, the CLI was fixed — delete this test and update "
        "test_merge_method_is_passed_through to the space-separated form"
    )


def test_a_failing_merge_subcommand_is_reported(mg, monkeypatch):
    """gh can refuse the merge itself (conflicts, permissions). That return code
    must reach the caller rather than being flattened to success."""
    monkeypatch.setattr(mg, "fetch_checks",
                        lambda pr: [{"name": "Test", "state": "SUCCESS"}])
    monkeypatch.setattr(mg.subprocess, "run", lambda args, *a, **k: Done(returncode=3))
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21"])

    assert mg.main() == 3


# --- merge_guard --wait ------------------------------------------------------

def test_wait_polls_while_checks_are_pending_then_decides(mg, monkeypatch, no_merge):
    """Mutation proving this: drop `transient=True` from the pending verdict and
    --wait stops on the first poll and refuses a PR whose CI is simply running.

    The earlier vacuous version of this guard treated 'no checks' as settled,
    which refused PR #24 outright while GitHub was still registering its run."""
    states = [
        [{"name": "Test", "state": "IN_PROGRESS"}],
        [{"name": "Test", "state": "IN_PROGRESS"}],
        [{"name": "Test", "state": "SUCCESS"}],
    ]
    polls = []

    def fetch(pr):
        polls.append(pr)
        return states[min(len(polls) - 1, len(states) - 1)]

    monkeypatch.setattr(mg, "fetch_checks", fetch)
    monkeypatch.setattr(mg.time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21", "--wait"])

    assert mg.main() == 0
    assert len(polls) == 3, "must keep polling until the checks settle"
    assert no_merge == [["gh", "pr", "merge", "21", "--merge"]]


def test_wait_gives_up_at_the_timeout_and_refuses(mg, monkeypatch, no_merge, capsys):
    """A guard that waits forever is a hung CI job; it must refuse, not merge."""
    monkeypatch.setattr(mg, "fetch_checks",
                        lambda pr: [{"name": "Test", "state": "IN_PROGRESS"}])
    monkeypatch.setattr(mg.time, "sleep", lambda s: None)
    clock = iter([0, 1, 10_000, 10_001, 10_002])
    monkeypatch.setattr(mg.time, "time", lambda: next(clock))
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21", "--wait", "--timeout", "5"])

    assert mg.main() == 1
    assert no_merge == [], "a timeout must refuse, never merge"
    assert "REFUSING" in capsys.readouterr().err


def test_without_wait_a_pending_check_is_refused_immediately(mg, monkeypatch, no_merge):
    polls = []
    monkeypatch.setattr(mg, "fetch_checks", lambda pr: polls.append(pr) or
                        [{"name": "Test", "state": "PENDING"}])
    monkeypatch.setattr(sys, "argv", ["merge_guard.py", "21"])

    assert mg.main() == 1
    assert len(polls) == 1, "without --wait the guard must not poll"


# --- deploy_freshness._fmt ---------------------------------------------------

@pytest.mark.parametrize("delta,expected", [
    (timedelta(hours=3), "3h"),
    (timedelta(hours=47), "47h"),
    (timedelta(hours=48), "2d"),
    (timedelta(days=10), "10d"),
])
def test_fmt_switches_to_days_at_48_hours(df, delta, expected):
    assert df._fmt(delta) == expected


# --- deploy_freshness.main ---------------------------------------------------

@pytest.fixture
def gh_stub(df, monkeypatch):
    def serve(head=None, runs=None):
        def fake_gh(args):
            if args[0] == "api":
                return json.dumps(head) if head else ""
            return json.dumps(runs if runs is not None else [])
        monkeypatch.setattr(df, "_gh", fake_gh)
    return serve


def test_main_returns_two_when_head_cannot_be_read(df, gh_stub, monkeypatch, capsys):
    """Mutation proving this: return 0 instead of 2 and an unreachable GitHub
    reads as 'deploy is fresh'. CON-VER-005 — 'could not determine' must not be
    reported as 'the values agree'. 2 is distinct from the 1 used for stale."""
    gh_stub(head=None)
    monkeypatch.setattr(sys, "argv", ["deploy_freshness.py", "--repo", "o/r"])

    assert df.main() == 2
    assert "could not read main's HEAD" in capsys.readouterr().err


def test_main_is_green_when_the_deployed_sha_matches(df, gh_stub, monkeypatch, capsys):
    sha = "a" * 40
    gh_stub(head={"sha": sha, "date": "2026-01-01T00:00:00Z"}, runs=[{"headSha": sha}])
    monkeypatch.setattr(sys, "argv", ["deploy_freshness.py", "--repo", "o/r"])

    assert df.main() == 0
    assert "matches main" in capsys.readouterr().out


def test_main_fails_when_the_deploy_is_stale(df, gh_stub, monkeypatch, capsys):
    old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat().replace("+00:00", "Z")
    gh_stub(head={"sha": "b" * 40, "date": old}, runs=[{"headSha": "c" * 40}])
    monkeypatch.setattr(sys, "argv", ["deploy_freshness.py", "--repo", "o/r"])

    assert df.main() == 1
    assert "deploy is stale" in capsys.readouterr().out


def test_no_successful_run_is_reported_as_no_deployment(df, gh_stub, monkeypatch, capsys):
    old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat().replace("+00:00", "Z")
    gh_stub(head={"sha": "d" * 40, "date": old}, runs=[])
    monkeypatch.setattr(sys, "argv", ["deploy_freshness.py", "--repo", "o/r"])

    assert df.main() == 1
    assert "no successful deployment found" in capsys.readouterr().out


def test_grace_hours_flag_reaches_the_decision(df, gh_stub, monkeypatch, capsys):
    """A 10h-old undeployed commit is stale at the 6h default and fine at 24h."""
    ten_h = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat().replace("+00:00", "Z")
    gh_stub(head={"sha": "e" * 40, "date": ten_h}, runs=[{"headSha": "f" * 40}])

    monkeypatch.setattr(sys, "argv", ["deploy_freshness.py", "--repo", "o/r"])
    assert df.main() == 1

    monkeypatch.setattr(sys, "argv",
                        ["deploy_freshness.py", "--repo", "o/r", "--grace-hours", "24"])
    assert df.main() == 0
    assert "grace period" in capsys.readouterr().out


def test_gh_helper_returns_stripped_stdout(df, monkeypatch):
    monkeypatch.setattr(df.subprocess, "run", lambda *a, **k: Done("  payload  \n"))
    assert df._gh(["api", "x"]) == "payload"
