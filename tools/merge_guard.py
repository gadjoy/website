"""Refuse to merge a pull request before its checks have finished and passed.

This exists because of a real incident in this repo: PRs #19 and #21 were both merged while
their checks were still running. Nothing prevented it, because `gh pr merge` merges on
request and branch protection — which is what would normally require a green check — is not
going to be enabled here.

So the rule is enforced on the way in instead. The decision is a pure function of the check
states, so it can be tested without GitHub, without a pull request, and without waiting for a
run to finish.

    python tools/merge_guard.py 21            # refuse unless everything is green
    python tools/merge_guard.py 21 --wait     # poll until the checks settle, then decide
"""
import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List

# gh reports these while a run is still going.
UNFINISHED = {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED"}
# ...and these when it has gone wrong. CANCELLED counts: a cancelled check never proved
# anything, and treating "not failed" as "passed" is how an ungated change lands.
BAD = {"FAILURE", "CANCELLED", "TIMED_OUT", "ERROR", "ACTION_REQUIRED", "STARTUP_FAILURE"}


@dataclass
class Verdict:
    ok: bool
    reason: str
    # True when the answer may still change on its own — checks running, or not yet
    # registered. A failure is never transient.
    transient: bool = False


def is_transient(verdict: "Verdict") -> bool:
    """Should `--wait` keep polling on this verdict?

    Yes while checks are running, and yes when none have appeared yet: GitHub takes a few
    seconds to register a run on a freshly-opened PR. That window bit in production on #24 —
    the guard refused outright rather than waiting. A guard that rejects a PR whose CI has
    simply not shown up yet is one people learn to bypass.
    """
    return verdict.transient


def decide_merge(checks: List[dict]) -> Verdict:
    """Is this pull request safe to merge?

    `checks` is what `gh pr checks --json name,state` returns. Anything not explicitly
    finished-and-good blocks the merge.
    """
    if not checks:
        return Verdict(False, (
            "no checks reported on this pull request. That is not the same as passing — it is "
            "the state this repo was in before the workflow existed. Confirm CI ran."),
            transient=True)

    failing = [c["name"] for c in checks if (c.get("state") or "").upper() in BAD]
    if failing:
        # Reported ahead of pending on purpose: saying "pending" would invite someone to
        # wait and retry, when the answer is already no.
        return Verdict(False, f"checks failing: {', '.join(sorted(failing))}")

    pending = [c["name"] for c in checks if (c.get("state") or "").upper() in UNFINISHED]
    if pending:
        return Verdict(False, f"checks still pending: {', '.join(sorted(pending))}",
                       transient=True)

    return Verdict(True, f"{len(checks)} check(s) green")


def fetch_checks(pr: int) -> List[dict]:
    out = subprocess.run(
        ["gh", "pr", "checks", str(pr), "--json", "name,state"],
        capture_output=True, text=True,
    )
    # gh exits non-zero when any check is failing, which is data rather than an error here.
    if not out.stdout.strip():
        return []
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pr", type=int)
    ap.add_argument("--wait", action="store_true", help="poll until the checks settle")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--merge-method", default="--merge",
                    choices=["--merge", "--squash", "--rebase"])
    ap.add_argument("--dry-run", action="store_true", help="decide, but do not merge")
    args = ap.parse_args()

    deadline = time.time() + args.timeout
    while True:
        verdict = decide_merge(fetch_checks(args.pr))
        if not is_transient(verdict) or not args.wait or time.time() > deadline:
            break
        print(f"  {verdict.reason} - waiting...", flush=True)
        time.sleep(20)

    if not verdict.ok:
        print(f"REFUSING to merge #{args.pr}: {verdict.reason}", file=sys.stderr)
        return 1

    print(f"#{args.pr}: {verdict.reason}")
    if args.dry_run:
        return 0
    merged = subprocess.run(["gh", "pr", "merge", str(args.pr), args.merge_method])
    return merged.returncode


if __name__ == "__main__":
    sys.exit(main())
