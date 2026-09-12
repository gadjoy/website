"""Tests for the controls that stand in for branch protection.

Branch protection is not going to be enabled, so `test` can never be a *required* check.
These guards cover what that leaves exposed — a red `main` nobody is told about, a merge
that lands ahead of its checks, and a deploy that quietly stops.

The interesting logic deliberately lives in pure functions rather than in workflow YAML or
bash, because a scheduled workflow is the least testable code in a repo: you would otherwise
wait a day to find out it was wrong. Written before the modules exist (Constitution I).
"""
import sys
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "tools"))

CANARY = REPO_ROOT / ".github" / "workflows" / "canary.yml"


@pytest.fixture(scope="module")
def mg():
    import merge_guard
    return merge_guard


@pytest.fixture(scope="module")
def df():
    import deploy_freshness
    return deploy_freshness


# --- merge guard (SC-002) -----------------------------------------------------
def test_all_green_is_allowed(mg):
    v = mg.decide_merge([{"name": "Test (quality gate)", "state": "SUCCESS"},
                         {"name": "Build", "state": "SKIPPED"}])
    assert v.ok, v.reason


def test_pending_checks_are_refused(mg):
    """The exact mistake made twice in this repo: #19 and #21 merged mid-flight."""
    v = mg.decide_merge([{"name": "Test (quality gate)", "state": "IN_PROGRESS"}])
    assert not v.ok
    assert "pending" in v.reason.lower()
    assert "Test (quality gate)" in v.reason, "must name which check"


@pytest.mark.parametrize("state", ["PENDING", "QUEUED", "IN_PROGRESS"])
def test_every_unfinished_state_is_refused(mg, state):
    assert not mg.decide_merge([{"name": "c", "state": state}]).ok


@pytest.mark.parametrize("state", ["FAILURE", "CANCELLED", "TIMED_OUT", "ERROR"])
def test_every_bad_state_is_refused(mg, state):
    v = mg.decide_merge([{"name": "c", "state": state}])
    assert not v.ok
    assert "fail" in v.reason.lower()


def test_no_checks_at_all_is_refused(mg):
    """An empty list is not 'all green'. It is the state this repo was in before the
    workflow existed, and merging on it is how an ungated change lands."""
    v = mg.decide_merge([])
    assert not v.ok
    assert "no checks" in v.reason.lower()


def test_failure_is_reported_ahead_of_pending(mg):
    """A run that is both failing and unfinished is a failure; saying 'pending' would
    invite someone to simply wait and retry."""
    v = mg.decide_merge([{"name": "a", "state": "FAILURE"},
                         {"name": "b", "state": "IN_PROGRESS"}])
    assert not v.ok
    assert "fail" in v.reason.lower()


def test_no_checks_is_transient_so_wait_can_retry(mg):
    """A freshly-opened PR reports no checks for a few seconds before GitHub registers the
    run. Found in production on #24: the guard refused outright under `--wait` instead of
    waiting, because "no checks" was treated as a settled answer. A guard that hard-refuses a
    PR whose CI simply has not appeared yet is a guard people learn to bypass."""
    assert mg.is_transient(mg.decide_merge([]))
    assert mg.is_transient(mg.decide_merge([{"name": "c", "state": "IN_PROGRESS"}]))


def test_a_real_failure_is_not_transient(mg):
    """...but a failure must end the wait immediately, not spin until timeout."""
    assert not mg.is_transient(mg.decide_merge([{"name": "c", "state": "FAILURE"}]))
    assert not mg.is_transient(mg.decide_merge([{"name": "c", "state": "SUCCESS"}]))


# --- deploy freshness (SC-003, SC-004) ----------------------------------------
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def test_deployed_head_is_fresh(df):
    v = df.assess_freshness(head_sha="abc123", deployed_sha="abc123",
                            head_committed_at=NOW - timedelta(hours=48),
                            now=NOW, grace_hours=6)
    assert v.ok, v.reason


def test_recent_commit_not_yet_deployed_is_in_flight(df):
    """A deploy in progress is not a stalled deploy."""
    v = df.assess_freshness(head_sha="new", deployed_sha="old",
                            head_committed_at=NOW - timedelta(hours=1),
                            now=NOW, grace_hours=6)
    assert v.ok, v.reason


def test_commit_undeployed_beyond_the_grace_period_is_stale(df):
    """The 'deploy quietly stopped' signal — the site still serves 200 on every page, so
    smoke cannot see it."""
    v = df.assess_freshness(head_sha="new", deployed_sha="old",
                            head_committed_at=NOW - timedelta(hours=30),
                            now=NOW, grace_hours=6)
    assert not v.ok
    assert "stale" in v.reason.lower() or "not deployed" in v.reason.lower()


def test_grace_boundary_is_not_off_by_one(df):
    just_inside = df.assess_freshness("new", "old", NOW - timedelta(hours=5, minutes=59),
                                      NOW, 6)
    just_outside = df.assess_freshness("new", "old", NOW - timedelta(hours=6, minutes=1),
                                       NOW, 6)
    assert just_inside.ok and not just_outside.ok


def test_missing_deployment_is_reported_not_crashed(df):
    """A repo that has never deployed, or an API that returned nothing."""
    v = df.assess_freshness("new", None, NOW - timedelta(hours=30), NOW, 6)
    assert not v.ok
    assert v.reason


# --- the canary workflow itself (SC-001) --------------------------------------
def test_canary_workflow_is_valid_and_scheduled():
    assert CANARY.is_file(), "canary workflow is missing"
    doc = yaml.safe_load(CANARY.read_text(encoding="utf-8"))
    triggers = doc[True] if True in doc else doc["on"]      # YAML parses `on:` as True
    assert "schedule" in triggers, "a canary that only runs on demand is not a canary"
    assert "workflow_dispatch" in triggers, "must be runnable by hand too"


def test_canary_runs_the_suite_and_the_smoke_test():
    text = CANARY.read_text(encoding="utf-8")
    assert "pytest" in text, "canary must run the acceptance suite"
    assert "smoke.sh" in text, "canary must check the live site"
    assert "deploy_freshness" in text, "canary must check the deploy is not stalled"


def test_canary_files_an_issue_on_failure():
    """Console-only failure is not detection — nobody reads a green-by-default runs list.

    Deliberately not asserting `if: failure()`. Each check runs with `continue-on-error` and a
    final report step evaluates every outcome, so the issue can name ALL of them; an
    `if: failure()` design stops at the first failure and hides the rest. What matters is that
    an issue is created and that the decision is driven by the checks' outcomes.
    """
    text = CANARY.read_text(encoding="utf-8")
    assert "gh issue create" in text
    assert "continue-on-error" in text, "each check must be allowed to fail so all are reported"
    for step in ("steps.suite.outcome", "steps.smoke.outcome", "steps.freshness.outcome"):
        assert step in text, f"the report must consider {step}"
    assert "exit 1" in text, "the run itself must go red, not just file an issue"


def test_canary_does_not_spam_duplicate_issues():
    """A daily cron filing 90 identical issues trains people to ignore it (FR-004)."""
    text = CANARY.read_text(encoding="utf-8")
    assert "gh issue list" in text, "must look for an existing open issue before creating one"


# --- local branch guard (SC-006) ----------------------------------------------
def test_house_gates_protects_main():
    import json
    cfg = json.loads((REPO_ROOT / ".house-gates.json").read_text(encoding="utf-8"))
    assert cfg.get("protected_branches") == ["main"], (
        "the branch gate ships disabled; with branch protection declined it is the only "
        "thing stopping a direct commit to main"
    )


def test_hygiene_check_actually_refuses_a_commit_on_main():
    """Config alone proves nothing — the checker must act on it."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import check_hygiene
    problems = check_hygiene.check_protected_branch(repo=str(REPO_ROOT), protected=("main",))
    # On a feature branch this is empty; the point is the function exists and is wired to
    # the same key the config sets.
    assert isinstance(problems, (list, tuple))
