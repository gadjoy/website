"""Notice when the site has quietly stopped deploying.

`scripts/smoke.sh` proves the live site answers correctly. It cannot prove the site is
*current* — if the pipeline stops, every page keeps returning 200 from the last good build and
the site simply ages. That failure mode is invisible to every other check in this repo.

Comparing the last successful deploy's commit against `main` catches it. The grace period
matters: a deploy that is merely in progress must not be reported as a stall, or the canary
cries wolf every morning and gets ignored.

    python tools/deploy_freshness.py --repo gadjoy/website
"""
import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

DEFAULT_GRACE_HOURS = 6


@dataclass
class Verdict:
    ok: bool
    reason: str


def assess_freshness(head_sha: str, deployed_sha: Optional[str],
                     head_committed_at: datetime, now: datetime,
                     grace_hours: int = DEFAULT_GRACE_HOURS) -> Verdict:
    """Has `main` been sitting undeployed for longer than a deploy could reasonably take?"""
    if deployed_sha and head_sha and deployed_sha == head_sha:
        return Verdict(True, f"deployed commit matches main ({head_sha[:8]})")

    age = now - head_committed_at
    if age <= timedelta(hours=grace_hours):
        return Verdict(True, (
            f"main ({head_sha[:8]}) is ahead of the deploy but only {_fmt(age)} old - "
            f"within the {grace_hours}h grace period, so a deploy is probably in flight"))

    if not deployed_sha:
        return Verdict(False, (
            f"no successful deployment found, and main ({head_sha[:8]}) is {_fmt(age)} old"))

    return Verdict(False, (
        f"deploy is stale: main is {head_sha[:8]} ({_fmt(age)} old) but the last successful "
        f"deploy was {deployed_sha[:8]}. The site is still serving, just not updating."))


def _fmt(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    return f"{hours:.0f}h" if hours < 48 else f"{hours / 24:.0f}d"


def _gh(args):
    out = subprocess.run(["gh"] + args, capture_output=True, text=True)
    return out.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--workflow", default="hugo.yml")
    ap.add_argument("--grace-hours", type=int, default=DEFAULT_GRACE_HOURS)
    args = ap.parse_args()

    head = json.loads(_gh(["api", f"repos/{args.repo}/commits/main",
                           "--jq", '{sha:.sha, date:.commit.committer.date}']) or "{}")
    runs = json.loads(_gh(["run", "list", "--repo", args.repo, "--workflow", args.workflow,
                           "--branch", "main", "--status", "success", "--limit", "1",
                           "--json", "headSha"]) or "[]")

    if not head:
        print("could not read main's HEAD", file=sys.stderr)
        return 2

    verdict = assess_freshness(
        head_sha=head["sha"],
        deployed_sha=runs[0]["headSha"] if runs else None,
        head_committed_at=datetime.fromisoformat(head["date"].replace("Z", "+00:00")),
        now=datetime.now(timezone.utc),
        grace_hours=args.grace_hours,
    )
    print(verdict.reason)
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
