"""Publish weekly repair decks into the site.

Two modes:

  --deck PATH           local: publish one deck file. No network, no credentials, so this is
                        the path used for rehearsal and for tests.
  --from-intake         read open `deck`-labelled issues from the private intake repo and
                        publish every deck they point at — either committed under `decks/`
                        (any size, and the only route the API can resolve) or dragged onto
                        the issue (capped at 25MB by GitHub).

Intake is a *private* repo because a photo dropped into a public issue is world-readable the
instant it posts and its attachment URL outlives the issue — and repair photos have been shown
to carry customer serials and IMEIs. All the work happens here in the public repo, where Actions
minutes are free and unlimited, reading intake through a read-only token.

Writes to the working tree only. Branching, committing and PR creation belong to the workflow,
so this stays a pure content generator that is easy to run by hand.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_to_posts import DeckFormatError, publish_deck  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTACHMENT_RE = re.compile(
    r"https://github\.com/user-attachments/files/[^\s)\"'>]+|"
    r"https://github\.com/[^/\s]+/[^/\s]+/files/\d+/[^\s)\"'>]+",
    re.I,
)
WEEK_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# A deck committed into the intake repo, referenced from the issue body. This is the path for
# decks over GitHub's 25MB issue-attachment cap, and the only one reachable through the public
# API — issue attachments live on a host with no API listing, so they can only be scraped out
# of the body text.
REPO_DECK_RE = re.compile(r"decks/[^\s`)\"'<>]+\.pptx?", re.I)


def _gh_json(url: str, token: str):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "gadjoy-deck-publisher",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _download(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "gadjoy-deck-publisher",
    })
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def _repo_file(intake: str, path: str, token: str) -> bytes:
    """Fetch a file committed in the intake repo.

    `application/vnd.github.raw` streams the bytes, which matters because the default JSON
    response base64-encodes and refuses anything over 1MB — and a week's deck is several.
    """
    req = urllib.request.Request(
        f"https://api.github.com/repos/{intake}/contents/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw",
            "User-Agent": "gadjoy-deck-publisher",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def collect_decks(intake: str, body: str, token: str):
    """Yield (name, bytes) for every deck an issue points at.

    Two routes, checked in order: a deck committed to `decks/` in this repo (works at any
    size, and is the only route the API can actually resolve), then a file dragged onto the
    issue.
    """
    for path in dict.fromkeys(REPO_DECK_RE.findall(body)):
        yield path.rsplit("/", 1)[-1], _repo_file(intake, path, token)
    for url in dict.fromkeys(ATTACHMENT_RE.findall(body)):
        name = url.rsplit("/", 1)[-1]
        if name.lower().endswith((".pptx", ".ppt")):
            yield name, _download(url, token)


def report_lines(deck_name, report) -> list:
    """Human-readable outcome. Posted back on the intake issue so the team sees exactly what
    happened, including what was redacted — silence would teach nothing."""
    out = [f"**{deck_name}**",
           f"- published: {len(report.published)}",
           f"- already present: {len(report.already_present)}",
           f"- slides skipped: {len(report.skipped)}"]
    for p in report.published:
        out.append(f"  - `{p.slug}`")
    if report.resurfaced_slugs:
        out.append("- ⚠️ these titles already exist on the site, so they were given a numeric "
                   "suffix. Check the deck is this week's and not a re-run:")
        for slug in report.resurfaced_slugs:
            out.append(f"  - `{slug}`")
    if getattr(report, "skipped_videos", None):
        out.append("- ℹ️ these slides had a **video** that was not published — the privacy "
                   "scan can read stills but not video frames, so clips are held back rather "
                   "than risk publishing a customer's screen:")
        for v in report.skipped_videos:
            out.append(f"  - `{v}`")
    if report.redactions:
        out.append("- **redacted customer identifiers** (publish a photo of the device, not its "
                   "About screen):")
        for slug, kinds in report.redactions.items():
            out.append(f"  - `{slug}`: {', '.join(kinds)}")
    for s in report.skipped:
        out.append(f"  - slide {s.slide}: {s.reason}")
    return out


def publish_local(deck: Path, date: str, issue: int, dry_run: bool) -> int:
    report = publish_deck(deck, date=date, issue=issue, out_root=REPO_ROOT, dry_run=dry_run)
    print("\n".join(report_lines(deck.name, report)))
    return 0


def _comment(intake: str, issue: int, body: str, token: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{intake}/issues/{issue}/comments",
        data=json.dumps({"body": body}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "gadjoy-deck-publisher",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=60).close()


def _close(intake: str, issue: int, token: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{intake}/issues/{issue}",
        data=json.dumps({"state": "closed"}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "gadjoy-deck-publisher",
        },
        method="PATCH",
    )
    urllib.request.urlopen(req, timeout=60).close()


def publish_from_intake(intake: str, dry_run: bool, notify: bool = False) -> int:
    token = os.environ.get("INTAKE_TOKEN")
    if not token:
        sys.exit("INTAKE_TOKEN is not set — it is required to read the private intake repo")

    issues = _gh_json(
        f"https://api.github.com/repos/{intake}/issues?state=open&labels=deck&per_page=50", token)
    if not issues:
        print("no open deck issues")
        return 0

    all_lines, failures, per_issue = [], [], {}
    for issue in issues:
        num, body = issue["number"], issue.get("body") or ""
        week = WEEK_RE.search(body)
        date = week.group(1) if week else os.environ.get("RUN_DATE", "")[:10]
        if not date:
            failures.append(f"issue #{num}: no week-ending date in the body")
            continue

        decks = list(collect_decks(intake, body, token))
        if not decks:
            failures.append(
                f"issue #{num}: no deck found. Attach the .pptx, or upload it to decks/ in "
                f"this repo and name it in the issue body.")
            continue

        for name, data in decks:
            tmp = Path(tempfile.gettempdir()) / name
            tmp.write_bytes(data)
            try:
                report = publish_deck(tmp, date=date, issue=num,
                                      out_root=REPO_ROOT, dry_run=dry_run)
            except DeckFormatError as exc:
                failures.append(f"issue #{num} ({name}): {exc}")
                continue
            all_lines += [f"_issue #{num}, week ending {date}_"]
            lines = report_lines(name, report)
            all_lines += lines + [""]
            per_issue.setdefault(num, []).extend(lines)

    # Tell the team what happened, on the issue they filed. Reporting the redactions is the
    # only way the "photograph the device, not its About screen" rule ever gets learned.
    if notify and not dry_run:
        for num, lines in per_issue.items():
            _comment(intake, num, "\n".join(
                ["Published to gadjoy.in:", ""] + lines +
                ["", "_Posted automatically by `publish-decks`._"]), token)
            if not failures:
                _close(intake, num, token)

    print("\n".join(all_lines) if all_lines else "nothing published")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", help="publish one local .pptx (no network)")
    ap.add_argument("--date", help="week-ending date, YYYY-MM-DD")
    ap.add_argument("--issue", type=int, default=0, help="intake issue number, for provenance")
    ap.add_argument("--from-intake", metavar="OWNER/REPO",
                    help="read open deck issues from the private intake repo")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--notify", action="store_true",
                    help="comment the outcome on the intake issue and close it")
    args = ap.parse_args()

    if args.deck:
        if not args.date:
            sys.exit("--date is required (the slide's own date is a stale placeholder)")
        return publish_local(Path(args.deck), args.date, args.issue, args.dry_run)
    if args.from_intake:
        return publish_from_intake(args.from_intake, args.dry_run, args.notify)
    ap.error("one of --deck or --from-intake is required")


if __name__ == "__main__":
    sys.exit(main())
