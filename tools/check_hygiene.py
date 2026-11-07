#!/usr/bin/env python3
"""house_gates.py — the local gates every repo in this house should have.

Stdlib only, no install, works on any stack. Two things it does:

    house_gates.py --audit [REPO]     read-only: which gates exist, which don't
    house_gates.py --install REPO     write the hooks and vendor this file

and one thing it *is* — the gate itself, run by the pre-commit hook:

    house_gates.py --hygiene          check the staged content, block on failure
    house_gates.py --message FILE     check a commit message says why

and one read-only report over a repo's working tree, for fleet audits:

    house_gates.py --ci-audit [REPO…] the workflow gate over .github/workflows/

Design borrowed from resumefit's `scripts/check-hygiene.sh`, which is the best
implementation in the house. Its three load-bearing ideas, kept:

  * **Staged content, not history.** A secret caught at commit never enters the
    repository. Catching it afterwards means rewriting history or rotating a
    credential — the damage is already done.
  * **Placeholders must pass.** A gate that fires on `API_KEY=<your-key>` trains
    people to bypass it, and a bypassed gate protects nothing.
  * **Exceptions are explicit and demand a reason.** `hygiene-ok: <why>` in a file
    (the tests for these gates must contain example keys, or they test nothing).

Nothing here is speculative hardening: each gate exists because the thing it
prevents has already happened in one of these projects. Keep it that way — a gate
without an incident behind it is the kind people delete.

hygiene-ok: this file is the scanner; it necessarily contains credential-shaped
patterns and the names of the constructs it flags.
"""
import contextlib
import fnmatch
import json
import os
import re
import subprocess
import sys

VERSION = "1.7.0"
MARKER = "house-gates"
CONFIG = ".house-gates.json"

# Per-repo configuration, because a blanket policy is one people disable. An
# art site legitimately commits 7 MB JPEGs; a data site commits a 47 MB JSON.
# Defaults are deliberately conservative: block what is nearly always a mistake
# (secrets), and leave what is a house *convention* (branching) opt-in, so
# installing gates never silently changes how someone works.
DEFAULTS = {
    "secrets": True,
    "message": True,
    "max_bytes": 512 * 1024,      # 0 disables the size gate
    "protected_branches": [],     # e.g. ["main"] — empty means "don't block"
    # Ported from resumefit, whose gate set is the richest in the house. Enabled
    # by the installer only when a repo actually has the thing they guard, since
    # a gate that cannot apply is noise.
    "determinism": False,
    "migrations": False,
    "artifacts": False,
    # Enabled by the installer when .github/workflows/ exists. See scan_workflow.
    "workflows": False,
    # Test code that builds git sandboxes must not inherit the hook's GIT_DIR.
    # See scan_git_env. Only added lines are judged, so it is safe to default on.
    "git_env": True,
    # Paths (fnmatch globs) allowed past the size gate, on top of LOCKFILES.
    "large_ok": [],
    # Whether the GitHub repository is private, written by the installer from
    # `gh repo view`. None means unknown: the hosted-runner check is then skipped
    # and says so, because unknown is not the same as fine (CON-VER-005).
    "private": None,
}

DENYLIST = ".house-gates.denylist"
# Lockfiles are generated, reviewed by diff, and legitimately large; blocking them
# taught resumefit (#52) and keepsake (#12, a font) to bypass the size gate.
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "uv.lock", "poetry.lock",
             "pnpm-lock.yaml", "yarn.lock", "Cargo.lock", "Pipfile.lock",
             "Gemfile.lock", "composer.lock", "go.sum"}

# ---------------------------------------------------------------- shell helpers


def git(*args, repo="."):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True).stdout


def staged_modes(repo="."):
    """{path: mode} for the index — 120000 is a symlink, whose blob is its target."""
    out = git("ls-files", "--stage", repo=repo)
    modes = {}
    for ln in out.split("\n"):
        parts = ln.split("\t", 1)
        if len(parts) == 2:
            modes[parts[1]] = parts[0].split(" ", 1)[0]
    return modes


def staged_files(repo="."):
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", repo=repo)
    return [f for f in out.split("\n") if f.strip()]


# ---------------------------------------------------------------- the gates


def load_config(repo="."):
    """DEFAULTS overlaid with the repo's .house-gates.json, if it has one."""
    cfg = dict(DEFAULTS)
    path = os.path.join(repo, CONFIG)
    if os.path.isfile(path):
        try:
            with open(path) as f:
                cfg.update(json.load(f))
        except (OSError, ValueError) as e:
            print(f"warning: ignoring unreadable {CONFIG}: {e}", file=sys.stderr)
    return cfg


# A value is a placeholder when it is obviously redacted, an env lookup, or an
# example. These must pass: see the module docstring.
PLACEHOLDER = re.compile(
    r"\.\.\.|xxx+|redacted|placeholder|example|changeme|dummy|sample|your[-_ ]|"
    r"synth|fake|test[-_]?(key|token|secret)|not[-_]?real|invalid|"
    r"<[a-z_ -]+>|\$\{?[A-Z_]+|os\.environ|process\.env|getenv|import\.meta\.env|"
    # A password for a database on the loopback interface is a CI service or a
    # dev container, not a credential: resumefit's ci.yml was refused for
    # `postgres:postgres@localhost`, which is the fixture every Postgres job uses.
    r"@(localhost|127\.0\.0\.1|\[::1\])\b",
    re.I)

# Shapes that are a credential or nothing. Kept few and specific: a broad regex
# produces false positives, and false positives are how a scanner gets ignored.
SECRET_PATTERNS = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
     "a private key block",
     "Remove it and rotate the key — anything that reached disk is compromised."),
    (re.compile(r'"type"\s*:\s*"service_account"'),
     "a GCP service account key",
     "Use Workload Identity Federation, and rotate this key if it ever existed."),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{24,}"),
     "an API key",
     "Move it to a secret manager and rotate it — assume it is compromised."),
    (re.compile(r"\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?)://"
                r"[^:/@\s]+:[^@\s]{8,}@"),
     "a database URL with a password in it",
     "Use an env var, and rotate the password."),
    (re.compile(r"(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*"
                r"[\"'][A-Za-z0-9_/+\-]{20,}[\"']", re.I),
     "what looks like a live credential",
     "Move it to a secret manager and rotate it."),
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
     "a GitHub token",
     "Revoke it at github.com/settings/tokens — it is compromised."),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
     "an AWS access key id",
     "Deactivate it in IAM and rotate — assume it is compromised."),
)

EXCEPTION = re.compile(r"hygiene-ok:\s*\S")

# Third-party code we did not write and do not control. Its sample values are not
# our secrets, and flagging them is how a scanner trains people to ignore it.
VENDORED = re.compile(r"(^|/)(themes|vendor|node_modules|third_party|"
                      r"site-packages|\.venv|venv)/")


_TOKEN_LEFT = re.compile(r"[\w.\-/]")


def _token_around(line, match):
    """The whole token a secret pattern matched in: back over the identifier it is
    part of, forward to the next whitespace. A placeholder is judged on this, never
    on the line — keepsake #11 found that a real key beside a comment saying it was
    'now invalid' passed, because the comment's word matched PLACEHOLDER."""
    start, end = match.start(), match.end()
    while start > 0 and _TOKEN_LEFT.match(line[start - 1]):
        start -= 1
    while end < len(line) and not line[end].isspace():
        end += 1
    return line[start:end]


def scan_secrets(path, content):
    """Problems in one staged file. `hygiene-ok: <reason>` exempts the file."""
    if EXCEPTION.search(content) or VENDORED.search(path):
        return []
    problems, reported = [], set()
    for pattern, what, advice in SECRET_PATTERNS:
        for line in content.split("\n"):
            m = pattern.search(line)
            if not m or PLACEHOLDER.search(_token_around(line, m)):
                continue
            excerpt = line.strip()[:72]
            # One line can match several patterns (an `sk-…` value is also a
            # `key = "…"`); report the line once, not once per pattern.
            if excerpt in reported:
                break
            reported.add(excerpt)
            problems.append((f"{path} contains {what}.", advice, excerpt))
            break                      # one report per pattern is enough
    return problems


# resumefit: "Counter.most_common() broke ties in set-iteration order: three
# workers, three different resumes, and a tracked score that moved on its own.
# Five days to notice." Only ADDED lines are examined, so existing code need not
# be rewritten to adopt this.
NONDETERMINISM = re.compile(
    r"\.most_common\(\)|\b(?:list|sorted)\(set\(|\bset\([^)]*\)\.pop\(\)")
NONDETERMINISM_OK = "nondeterminism-ok:"


def scan_determinism(path, repo=".", content=None):
    if not path.endswith(".py"):
        return []
    if content and EXCEPTION.search(content):
        return []
    diff = git("diff", "--cached", "-U0", "--", path, repo=repo)
    for line in diff.split("\n"):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        if NONDETERMINISM_OK in body:
            continue
        # A comment or a docstring line describing the pattern is not the pattern.
        # This file flagged itself on the comment explaining this very gate.
        stripped = body.strip()
        if stripped.startswith(("#", '"', "'", "*")):
            continue
        if NONDETERMINISM.search(body):
            return [(f"{path} adds ordering-dependent code.",
                     "Break ties on an explicit key, or mark the line "
                     f"'# {NONDETERMINISM_OK} <reason>'.",
                     body.strip()[:72])]
    return []


# resumefit: "0005 blanked data and was safe only because a fresh dump was taken
# first. Nothing enforced it."
DESTRUCTIVE_SQL = re.compile(
    r"\b(?:DROP|TRUNCATE)\b|\bDELETE\s+FROM\b|\bUPDATE\b.*\bSET\b", re.I)


def scan_migration(path, content):
    if "migrations/" not in path or not path.endswith(".sql"):
        return []
    code = "\n".join(ln for ln in content.split("\n")
                     if not ln.strip().startswith("--"))
    if not DESTRUCTIVE_SQL.search(code):
        return []
    if re.search(r"^\s*--.*backup", content, re.I | re.M):
        return []
    return [(f"{path} is destructive but names no backup.",
             "Take a dump, confirm it covers the affected rows, then add: "
             "-- backup: <dump name> taken immediately before this.", "")]


GENERATED = (".docx", ".pdf", ".dump", ".sqlite", ".db")


# resumefit, 2026-09-27: every test in check-hygiene.sh was `printf '%s' "$x" |
# grep -q …` under `set -o pipefail`. grep -q exits on its first match; if the
# writer has not finished, it takes SIGPIPE and the pipeline reports *its*
# failure — so a `hygiene-ok:` waiver read as absent and a legitimate example
# key was refused. Below 64 KiB it depends on scheduling (three of eight full
# runs on a loaded VM), above it every time. `grep -q … <<< "$x"` has no pipe.
PIPE_TO_GREP_Q = re.compile(r"\|\s*grep\s+(?:-[A-Za-z]*q[A-Za-z]*|--quiet|--silent)\b")
PIPEFAIL_OK = "pipefail-ok:"
SHELL_PATH = re.compile(r"\.(?:sh|bash)$")
SHEBANG = re.compile(r"^#!.*\b(?:ba|z|da)?sh\b")


def scan_shell(path, content):
    """A `| grep -q` under pipefail is a race, not a test (see PIPE_TO_GREP_Q)."""
    if not (SHELL_PATH.search(path) or SHEBANG.match(content)):
        return []
    if EXCEPTION.search(content) or not re.search(r"\bpipefail\b", content):
        return []
    problems = []
    for n, line in enumerate(content.split("\n"), 1):
        # A comment line is prose, not a pipeline: the gate once refused a commit whose
        # only match was the comment explaining the here-string below it (viveka #30).
        if line.lstrip().startswith("#"):
            continue
        if PIPE_TO_GREP_Q.search(line) and PIPEFAIL_OK not in line:
            problems.append((f"{path}:{n} has grep -q at the end of a pipeline under pipefail.",
                             "grep -q exits on the first match; the writer then dies of "
                             "SIGPIPE and pipefail reports the pipeline as failed — a "
                             "check that flips with timing. Use `grep -q … <<< \"$x\"` "
                             f"(no pipe), or mark the line `# {PIPEFAIL_OK} <why the "
                             "writer survives EPIPE>`.",
                             line.strip()[:72]))
            break
    return problems


# resumefit #40 and landseer #56, 2026-09-27: a linked worktree's `venv` symlink
# to the main checkout's absolute path was committed — `.gitignore`'s `venv/`
# ignores a directory, not a symlink of that name — and `uv venv` in CI failed on
# it. A symlink into one machine's filesystem is never portable content.
def scan_symlink(path, mode, target):
    if mode != "120000" or not target.strip().startswith("/"):
        return []
    return [(f"{path} is a symlink to an absolute path.",
             "It points into one machine's filesystem; nobody else, and no "
             "runner, has that path. Unstage it (`git rm --cached`) and ignore "
             "the name without a trailing slash so the symlink form is covered.",
             target.strip()[:72])]


def scan_artifact(path):
    if path.startswith(("docs/", "public/")) or VENDORED.search(path):
        return []
    if path.endswith(GENERATED):
        return [(f"{path} is a generated/binary artifact.",
                 "Generated files belong in storage or are rebuilt on demand — "
                 "git history cannot be cleaned later.", "")]
    return []


# keepsake, 2026-11-07 (and resumefit, 2026-09-26): git exports GIT_DIR,
# GIT_INDEX_FILE and friends to every hook, absolute from a linked worktree. A test
# suite run from the hook built its sandbox with `git init` in a temp dir — and
# acted on the REAL repository instead: config set bare, hook path blanked, the
# branch being pushed replaced by fixture commits, origin/main moved. The hook
# template now scrubs (see PRE_COMMIT), but a suite run any other way from a hook
# environment is still exposed, so test code that mutates a git repository must
# scrub too, or say why it need not.
TEST_FILE = re.compile(
    r"(^|/)(tests?|e2e|spec|specs|__tests__)/.*\.(py|sh|bash|js|jsx|ts|tsx|mjs|cjs)$"
    r"|(^|/)test_[^/]*\.py$|_test\.py$"
    r"|\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)$")
_GIT_WORD = re.compile(r"(?<![\w-])git(?![\w-])")
_GIT_MUTATES = re.compile(r"(?<![\w-])(init|commit|config|update-ref)(?![\w-])")
GIT_SCRUB = re.compile(
    r"startswith\(\s*[\"']GIT_|local-env-vars|unset\s+[\"']?GIT_|env\s+-u\s+GIT_|"
    r"del\s+os\.environ\[\s*[\"']GIT_|os\.environ\.pop\(\s*[\"']GIT_|"
    r"delete\s+(?:process\.)?env\.GIT_",
    re.I)
GIT_ENV_OK = re.compile(r"git-env-ok:\s*\S")


def scan_git_env(path, content, added=None, context=""):
    """Test code that runs a mutating git command with no GIT_* scrub in sight.

    `added` limits the judgement to those lines (the staged diff); `context` is the
    text of shared setup files (conftest.py, helpers) that may do the scrub for it.
    A heuristic, so it carries a waiver: `git-env-ok: <why>` anywhere in the file.
    `hygiene-ok:` deliberately does not waive it — that marker is for secrets.
    """
    if not TEST_FILE.search(path) or VENDORED.search(path):
        return []
    if GIT_ENV_OK.search(content) or GIT_SCRUB.search(content) or GIT_SCRUB.search(context):
        return []
    lines = added if added is not None else content.split("\n")
    for line in lines:
        code = line.strip()
        if code.startswith(("#", "//", "*", '"""', "'''")):
            continue
        if _GIT_WORD.search(code) and _GIT_MUTATES.search(code):
            return [(f"{path} runs git in test code with the inherited GIT_* environment.",
                     "Run from a hook, GIT_DIR points at the real repository and this "
                     "acts on it (keepsake, 2026-11-07). Pass an env with every GIT_* "
                     "removed, or mark the file `git-env-ok: <why>`.",
                     code[:72])]
    return []


def load_denylist(repo="."):
    """Personal values that must never be committed: one per line, `#` comments,
    entries shorter than 4 characters ignored (they would match everywhere)."""
    path = os.environ.get("HOUSE_GATES_DENYLIST") or os.path.join(repo, DENYLIST)
    try:
        with open(path, errors="replace") as f:
            raw = f.read().split("\n")
    except OSError:
        return []
    return [v.strip() for v in raw
            if v.strip() and not v.strip().startswith("#") and len(v.strip()) >= 4]


def scan_denylist(path, content, values):
    """vital-mosaic #59, #64, #65 (2026-11-04): the owner's real health values were
    copied into test fixtures and three PRs merged them. The values themselves
    are never printed — the report names the file, the line and the entry number."""
    if not values or VENDORED.search(path):
        return []
    problems = []
    for n, line in enumerate(content.split("\n"), 1):
        for i, value in enumerate(values, 1):
            if value in line:
                problems.append((f"{path}:{n} contains entry {i} of the personal-data "
                                 "denylist.",
                                 "Replace it with a synthetic value. Real personal data "
                                 "never belongs in a repository (CON-SEC-005).", ""))
                break
        if len(problems) >= 5:
            break
    return problems


# September 2026: the private repos in this house billed 2,197 of the 2,000 free
# GitHub Actions minutes in 30 days. One macOS job (billed at 10x) was about half
# of it; no job in any private repo had a timeout, so a single hung macOS job
# could have cost 3,600 on its own; three repos tested every merge commit twice
# (push + pull_request, or push + a deploy that re-ran CI). On a $0 spending
# limit the failure mode is every gate in every private repo going dark at once
# until month end. Four checks, each a line-based read of the YAML (the fleet's
# workflows are uniformly 2-space indented, and PyYAML is not stdlib).
WORKFLOW_PATH = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
MACOS_OK = "macos-ok:"
DOUBLE_RUN_OK = "double-run-ok:"


def _top_block(lines, key):
    """The lines under a top-level `key:` mapping, up to the next top-level key."""
    out, inside = [], False
    for ln in lines:
        if re.match(rf"^{key}:\s*(#.*)?$", ln):
            inside = True
            continue
        if inside and re.match(r"^\S", ln):
            break
        if inside:
            out.append(ln)
    return out


def _workflow_jobs(lines):
    """[(name, body_lines)] for each key two spaces under the top-level `jobs:`."""
    jobs, cur = [], None
    for ln in _top_block(lines, "jobs"):
        m = re.match(r"^  ([A-Za-z_][\w-]*):\s*(#.*)?$", ln)
        if m:
            cur = (m.group(1), [])
            jobs.append(cur)
        elif cur is not None:
            cur[1].append(ln)
    return jobs


def _push_reaches_default(on_lines):
    """Does the `on:` block fire on a push to main/master?

    `push:` with no filter is every branch; `branches:` naming main/master is;
    `push:` with only a `tags:` filter is *not* (GitHub runs it for tags only).
    """
    push, inside = [], False
    for ln in on_lines:
        if re.match(r"^  push:\s*(#.*)?$", ln):
            inside = True
            continue
        if inside and re.match(r"^  \S", ln):
            break
        if inside:
            push.append(ln)
    if not inside:
        return False
    text = "\n".join(push)
    if "branches" not in text:
        return "tags" not in text
    return bool(re.search(r"branches:.*\b(main|master)\b", text)
                or re.search(r"^\s+-\s*[\"']?(main|master)[\"']?\s*$", text, re.M))


RUNNER_OK = "runner-ok:"
_TOP_KEY = re.compile(r"^[A-Za-z_][\w-]*:(\s|$)")
_BROWSER_INSTALL = re.compile(r"playwright\s+install|npx\s+playwright|"
                              r"puppeteer\s+browsers\s+install")
# A versioned label anywhere in runs-on, including the VM pattern's fallback
# (gadjoy: `CI_RUNS_ON || "ubuntu-24.04"`). `ubuntu-latest` never matches.
_VERSIONED_LABEL = re.compile(r"(?<![\w-])(ubuntu|windows|macos)-\d")
_RUNS_WHEN_RED = re.compile(r"\bif:.*\b(failure|always)\(\)")
_REPORTS = re.compile(r"gh\s+issue\b|issues\.create|createComment|create-issue|"
                      r"github-script|gh\s+api\s+\S*issues|/issues\b", re.I)


def _job_steps(body):
    """[(keys, text)] for each `- ` item six spaces in, under the job's steps."""
    steps, cur = [], None
    for b in body:
        m = re.match(r"^      - ([\w-]+):", b) or re.match(r"^      -\s*$", b)
        if m:
            cur = [set([m.group(1)]) if m.groups() else set(), [b]]
            steps.append(cur)
            continue
        if cur is None:
            continue
        if b.strip() and not b.startswith("       "):
            cur = None
            continue
        k = re.match(r"^        ([\w-]+):", b)
        if k:
            cur[0].add(k.group(1))
        cur[1].append(b)
    return [(keys, "\n".join(text)) for keys, text in steps]


def _runs_on(body):
    """The runs-on line and any list items under it."""
    out, inside = [], False
    for b in body:
        if re.match(r"^    runs-on:", b):
            inside = True
            out.append(b)
            continue
        if inside and b.startswith("      "):
            out.append(b)
            continue
        inside = False
    return "\n".join(out)


def _container_pinned(body):
    """True when the job runs in a container whose image names a fixed tag."""
    image = None
    for i, b in enumerate(body):
        m = re.match(r"^    container:\s*(\S.*)?$", b)
        if not m:
            continue
        image = (m.group(1) or "").strip()
        if not image:
            for c in body[i + 1:]:
                if c.strip() and not c.startswith("      "):
                    break
                im = re.match(r"^      image:\s*(\S+)", c)
                if im:
                    image = im.group(1)
        break
    if not image:
        return False
    image = image.strip("\"'")
    if "${{" in image or "@sha256:" in image:
        return True
    tag = image.rsplit("/", 1)[-1]
    return ":" in tag and tag.rsplit(":", 1)[1] not in ("", "latest")


def scan_workflow(path, content, private=None):
    """Problems in one workflow file. `hygiene-ok: <reason>` exempts the file.

    `private` is the repository's visibility (True/False), or None when unknown —
    the hosted-runner check needs it and is skipped, not passed, without it."""
    if not WORKFLOW_PATH.match(path) or EXCEPTION.search(content):
        return []
    lines = content.split("\n")
    problems = []
    jobs = _workflow_jobs(lines)

    # 0. A file GitHub cannot run is a gate that silently does nothing: portfolio
    #    #87 ran zero jobs for a week (a `run:` step given a `with:` block) and
    #    cloudsweep #49 broke the whole file with a script at column 0. The parser
    #    is line-based on purpose (stdlib only), so these are the shapes that
    #    actually happened, not a YAML validator.
    # A tab at column 0, or in front of a key, is indentation and fatal. A tab
    # later in a block scalar's content (a Makefile recipe in a heredoc) is text.
    tabbed = next((n for n, ln in enumerate(lines, 1)
                   if re.match(r"^\t|^ *\t+[\w\"'-]+\s*:", ln)), None)
    if tabbed:
        problems.append((f"{path}:{tabbed} indents with a tab, which YAML forbids.",
                         "GitHub rejects the file and runs no job. Indent with spaces.",
                         lines[tabbed - 1].strip()[:72]))
    stray = next((n for n, ln in enumerate(lines, 1)
                  if ln and not ln[0].isspace() and not ln.startswith("#")
                  and ln.strip() not in ("---", "...") and not _TOP_KEY.match(ln)), None)
    if stray:
        problems.append((f"{path}:{stray} is not valid YAML: a line at column 0 that is "
                         "not a top-level key.",
                         "A block scalar's lines must be indented under their key; "
                         "otherwise the file fails to parse and no job runs.",
                         lines[stray - 1].strip()[:72]))
    if not jobs:
        problems.append((f"{path} defines no jobs.",
                         "A workflow with no `jobs:` (or none GitHub can read) runs "
                         "nothing and reports nothing — it looks like a passing gate.", ""))
    for name, body in jobs:
        for keys, text in _job_steps(body):
            if "run" in keys and "with" in keys:
                problems.append((f"{path}: job '{name}' has a `run:` step with a `with:` "
                                 "block.",
                                 "`with:` belongs to a `uses:` step; GitHub rejects the "
                                 "file and runs no job (portfolio #87).",
                                 text.split("\n")[0].strip()[:72]))
                break

    # 1. Every job bounded. A reusable-workflow call (`uses:`) cannot carry a
    #    timeout of its own; the timeouts live inside the called workflow.
    unbounded = [name for name, body in jobs
                 if not any(re.match(r"^    uses:", b) for b in body)
                 and not any(re.match(r"^    timeout-minutes:", b) for b in body)]
    if unbounded:
        problems.append((f"{path}: job(s) without timeout-minutes: "
                         f"{', '.join(unbounded)}.",
                         "The default is 6 hours; a hung macOS job bills 3,600 "
                         "minutes. Add `timeout-minutes:` to every job.", ""))

    # 2. Superseded runs cancellable (CI) or queued (deploys) — either way, a
    #    concurrency group. Top-level, or on every job.
    top = any(re.match(r"^concurrency:", ln) for ln in lines)
    per_job = jobs and all(any(re.match(r"^    concurrency:", b) for b in body)
                           for _, body in jobs)
    if not top and not per_job:
        problems.append((f"{path} has no concurrency group.",
                         "Add `concurrency: {group: ci-${{ github.workflow }}-"
                         "${{ github.ref }}, cancel-in-progress: true}` — for a "
                         "deploy, cancel-in-progress: false.", ""))

    # 3. A 10x runner only by deliberate opt-in, with the reason on the line.
    for name, body in jobs:
        if any(MACOS_OK in b for b in body):
            continue
        runs_on = [b for b in body if re.match(r"^    runs-on:", b)]
        on_macos = any(re.search(r"macos", b, re.I) for b in runs_on) or (
            any("matrix" in b for b in runs_on)
            and any(re.search(r"macos-", b, re.I) for b in body))
        if on_macos:
            problems.append((f"{path}: job '{name}' runs on macOS (bills 10x).",
                             "Gate it on a tag, label or dispatch and mark the "
                             f"job `# {MACOS_OK} <why it must be macOS>`.",
                             runs_on[0].strip()[:72] if runs_on else ""))

    # 5. A `container:` job runs as root unless told otherwise. On a self-hosted
    #    runner the root-owned files it leaves in the workspace break every later
    #    job of that repo (cloudsweep, 2026-09-26: `_work` had to be wiped by
    #    hand). Require an explicit `--user` in the container options.
    for name, body in jobs:
        start = next((i for i, b in enumerate(body) if re.match(r"^    container:", b)), None)
        if start is None:
            continue
        block = [body[start]]
        for b in body[start + 1:]:
            if b.strip() and not b.startswith("      "):
                break
            block.append(b)
        if not any("--user" in b for b in block):
            problems.append((f"{path}: job '{name}' has a container without --user.",
                             "It runs as root and leaves root-owned files behind on a "
                             "self-hosted runner. Add `options: --user 1001:1001` "
                             "(the runner's uid on GitHub-hosted and on the VM).",
                             body[start].strip()[:72]))

    for name, body in jobs:
        text = "\n".join(body)
        is_call = any(re.match(r"^    uses:", b) for b in body)
        on_macos = bool(re.search(r"macos", _runs_on(body), re.I)) or MACOS_OK in text
        if is_call or RUNNER_OK in text:
            continue

        # 6. A private repo's Linux jobs run on the VM. Since 2026-09-27 every one
        #    should; vital-mosaic's `specs` job, written a week after the move with a
        #    bare `ubuntu-latest`, billed hosted minutes for five weeks unnoticed, as
        #    did resumefit's `images` job (fleet audit, 2026-11-07).
        runs_on = _runs_on(body)
        # A matrix-driven runs-on is judged on the matrix it reads from.
        where = text if "matrix" in runs_on else runs_on
        if "matrix" in runs_on and re.search(r"macos-", text, re.I):
            on_macos = True
        if (private is True and runs_on and not on_macos
                and "CI_RUNS_ON" not in where and "self-hosted" not in where):
            problems.append((f"{path}: job '{name}' runs on GitHub-hosted minutes in a "
                             "private repo.",
                             "Use `runs-on: ${{ fromJSON(vars.CI_RUNS_ON || "
                             "'\"ubuntu-latest\"') }}` like every other job, or mark "
                             f"the job `# {RUNNER_OK} <why it must be hosted>`.",
                             runs_on.split("\n")[0].strip()[:72]))

        # 7. A browser install on a label GitHub can move. ubuntu-latest became
        #    26.04 around 2026-10-30 and Playwright refused to install there:
        #    gadjoy, folio, trailward and portfolio each broke and each fixed it
        #    differently. The VM pattern does not help — its fallback is the same
        #    moving label. Pin the image (the fleet uses the Playwright container
        #    at the lockfile's version) or a versioned runner label.
        if (not on_macos and _BROWSER_INSTALL.search(text)
                and not _container_pinned(body)
                and not _VERSIONED_LABEL.search(runs_on)):
            problems.append((f"{path}: job '{name}' installs a browser on a moving runner "
                             "image.",
                             "Run it in `mcr.microsoft.com/playwright:v<lockfile version>-"
                             "noble` with `--user 1001:1001`, or pin `runs-on` to a "
                             f"versioned label, or mark the job `# {RUNNER_OK} <why>`.",
                             runs_on.split("\n")[0].strip()[:72]))

    # 8. A scheduled run that fails tells nobody: GitHub mails only the last person
    #    to edit the cron. trailward's weekly refresh was red for 12 weeks,
    #    gadjoy's nightly secret scan for 25 days, artbypriti's health check for
    #    four Mondays, all unseen. A scheduled workflow must report its failure.
    on = _top_block(lines, "on")
    if any(re.match(r"^  schedule:", ln) for ln in on):
        # A reporter must run when the work failed: a job or step gated on
        # failure() or always() that files an issue, or a reusable reporter
        # workflow (trailward's report-failure.yml). A step with no `if:` runs only
        # on success, so it can never report a failure.
        reported = False
        for name, body in jobs:
            text = "\n".join(body)
            if re.search(r"^    uses:.*(report|notify|failure)", text, re.M | re.I):
                reported = True
            job_gate = any(_RUNS_WHEN_RED.search(b) for b in body
                           if re.match(r"^    if:", b))
            if job_gate and _REPORTS.search(text):
                reported = True
            for _keys, step in _job_steps(body):
                if _RUNS_WHEN_RED.search(step) and _REPORTS.search(step):
                    reported = True
                # The outcome collector (gadjoy's canary): checks run with
                # continue-on-error, and an unconditional step reads their outcomes
                # and files the issue. Steps BEFORE the checks can still fail
                # unreported; that residue is the repo's to close.
                if (re.search(r"steps\.[\w-]+\.outcome", step)
                        and _REPORTS.search(step) and "continue-on-error" in text):
                    reported = True
        if not reported:
            problems.append((f"{path}: scheduled workflow never reports a failure to "
                             "anyone.",
                             "Add a final step `if: failure()` that opens or comments on "
                             "an issue (`gh issue create …`, needs `issues: write`). "
                             "GitHub's own mail reaches only whoever last edited the cron.",
                             ""))

    # 4. The same commit tested twice: push to the default branch AND
    #    pull_request in one workflow. deploy.yml is the post-merge gate.
    if (DOUBLE_RUN_OK not in content and _push_reaches_default(on)
            and any(re.match(r"^  pull_request:", ln) for ln in on)):
        problems.append((f"{path} runs on both push (default branch) and "
                         "pull_request.",
                         "Every merge is tested twice. Drop the push trigger, or "
                         f"mark the file `# {DOUBLE_RUN_OK} <reason>`.", ""))
    return problems


def ci_audit(repo="."):
    """scan_workflow over the working tree, not the index — for fleet reports."""
    wf = os.path.join(repo, ".github", "workflows")
    problems = []
    if not os.path.isdir(wf):
        return problems
    private = load_config(repo).get("private")
    for name in sorted(os.listdir(wf)):
        if not name.endswith((".yml", ".yaml")):
            continue
        try:
            with open(os.path.join(wf, name), errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        problems += scan_workflow(f".github/workflows/{name}", content, private)
    return problems


PRIVATE_UNKNOWN = ("hosted-runner check not checked: {cfg} does not record whether the "
                   "repository is private (re-run --install where `gh` is signed in, "
                   "or set \"private\" by hand)")


def ci_audit_notes(repo="."):
    """What --ci-audit could not judge. Said out loud, never counted as clean."""
    if not os.path.isdir(os.path.join(repo, ".github", "workflows")):
        return []
    if load_config(repo).get("private") is None:
        return [PRIVATE_UNKNOWN.format(cfg=CONFIG)]
    return []


def check_protected_branch(repo=".", protected=()):
    if not protected:
        return []
    branch = git("rev-parse", "--abbrev-ref", "HEAD", repo=repo).strip()
    if branch in protected:
        return [(f"you are on '{branch}'. Work belongs on a branch.",
                 "git switch -c feat/my-change   # your staged work comes with you",
                 "")]
    return []


def size_exempt(path, large_ok=()):
    """Lockfiles always, plus whatever the repo's config declares (fnmatch globs)."""
    return (os.path.basename(path) in LOCKFILES
            or any(fnmatch.fnmatch(path, pat) for pat in large_ok or ()))


def check_size(path, repo=".", max_bytes=512 * 1024, large_ok=()):
    if not max_bytes or size_exempt(path, large_ok):
        return []
    sha = git("rev-parse", f":{path}", repo=repo).strip()
    if not sha:
        return []
    size = git("cat-file", "-s", sha, repo=repo).strip()
    if size.isdigit() and int(size) > max_bytes:
        return [(f"{path} is {int(size):,} bytes (limit {max_bytes:,}).",
                 "Large artifacts belong in storage, not in git history — "
                 "they cannot be removed from it later.", "")]
    return []


def is_probably_binary(path, repo="."):
    """git reports '-' for added/removed lines on a binary file."""
    line = git("diff", "--cached", "--numstat", "--", path, repo=repo)
    return line.startswith("-\t")


SHARED_SETUP = ("conftest.py", "helpers.py", "helpers.ts", "setup.ts", "setup.js")


def _added_lines(path, repo="."):
    diff = git("diff", "--cached", "-U0", "--", path, repo=repo)
    return [ln[1:] for ln in diff.split("\n")
            if ln.startswith("+") and not ln.startswith("+++")]


def _shared_setup(path, repo="."):
    """Index text of the setup files that may scrub GIT_* for a test file:
    conftest.py and friends in its own directory and every parent."""
    parts, texts = path.split("/")[:-1], []
    for depth in range(len(parts), -1, -1):
        base = "/".join(parts[:depth])
        for name in SHARED_SETUP:
            rel = f"{base}/{name}" if base else name
            texts.append(git("show", f":{rel}", repo=repo))
    return "\n".join(texts)


def hygiene(repo=".", cfg=None):
    """Every problem with the staged content. Empty means the commit may proceed."""
    cfg = dict(DEFAULTS, **(cfg or load_config(repo)))
    problems = list(check_protected_branch(repo, cfg["protected_branches"]))
    modes = staged_modes(repo)
    denylist = load_denylist(repo)
    warned_private = False
    for path in staged_files(repo):
        if os.path.basename(path) == DENYLIST:
            problems.append((f"{path} is the personal-data denylist and must never be "
                             "committed.",
                             f"Unstage it (`git rm --cached {path}`); --install adds it "
                             "to .gitignore.", ""))
            continue
        if modes.get(path) == "120000":
            problems += scan_symlink(path, "120000", git("show", f":{path}", repo=repo))
            continue
        problems += check_size(path, repo, cfg["max_bytes"], cfg.get("large_ok"))
        # Before the binary skip: the artifacts this gate stops ARE binaries, and
        # until 1.7.0 it could never fire on them (keepsake #11).
        if cfg["artifacts"]:
            problems += scan_artifact(path)
        if is_probably_binary(path, repo):
            continue
        content = git("show", f":{path}", repo=repo)
        if not content:
            continue
        problems += scan_denylist(path, content, denylist)
        if cfg["secrets"]:
            problems += scan_secrets(path, content)
        if cfg["determinism"]:
            problems += scan_determinism(path, repo, content)
        if cfg["migrations"]:
            problems += scan_migration(path, content)
        if cfg["workflows"]:
            problems += scan_workflow(path, content, cfg.get("private"))
            if (cfg.get("private") is None and WORKFLOW_PATH.match(path)
                    and not warned_private):
                warned_private = True
                print("house-gates: " + PRIVATE_UNKNOWN.format(cfg=CONFIG),
                      file=sys.stderr)
        if cfg.get("shell", True):
            problems += scan_shell(path, content)
        # Cheap first pass on the file alone; the diff and the shared setup files
        # are read only when the file really runs a mutating git with no scrub.
        if (cfg.get("git_env", True) and TEST_FILE.search(path)
                and scan_git_env(path, content)):
            problems += scan_git_env(path, content, _added_lines(path, repo),
                                     _shared_setup(path, repo))
    return problems


# A message that says only what changed is a message someone has to reverse-
# engineer later. The bar is deliberately low: some prose beyond the subject.
def check_message(text):
    lines = [ln for ln in text.split("\n") if not ln.startswith("#")]
    subject = (lines[0] if lines else "").strip()
    body = "\n".join(lines[1:]).strip()
    if not subject:
        return ["the commit message is empty."]
    if subject.lower().startswith(("wip", "fixup!", "squash!", "merge ")):
        return []                       # not meant to survive, or not authored
    if len(subject) < 10:
        return [f"the subject {subject!r} says too little."]
    if not body:
        return ["the commit message has no body — say *why*, not just what. "
                "The reason is the part nobody can recover later."]
    return []


# ---------------------------------------------------------------- audit

def detect_stack(repo):
    """Best-effort, and deliberately generous: a repo whose Python lives in
    backend/ or server/ is still a Python repo, and reporting "unknown" makes the
    audit look broken rather than the repo."""
    def has(*names):
        return any(os.path.exists(os.path.join(repo, n)) for n in names)

    def anywhere(suffix, limit=4):
        """Does a file with this suffix exist within `limit` levels?"""
        for root, dirs, files in os.walk(repo):
            depth = root[len(repo):].count(os.sep)
            if depth >= limit:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs
                       if d not in (".git", "node_modules", ".venv", "venv",
                                    "__pycache__", ".build", "vendor", "themes")]
            if any(f.endswith(suffix) for f in files):
                return True
        return False

    stack = []
    if (has("pyproject.toml", "requirements.txt", "setup.py", "manage.py")
            or anywhere(".py")):
        stack.append("python")
    if has("package.json"):
        stack.append("js")
    if has("hugo.toml", "hugo.yaml", "hugo.yml", "config.toml"):
        stack.append("hugo")
    if has("Package.swift", "project.yml") or anywhere(".swift"):
        stack.append("swift")
    if has("Dockerfile", "compose.dev.yaml", "docker-compose.yml"):
        stack.append("docker")
    return stack or ["unknown"]


def audit(repo):
    """What this repo has and lacks. Read-only."""
    def has_file(*names):
        return any(os.path.exists(os.path.join(repo, n)) for n in names)

    def grep(path, needle):
        p = os.path.join(repo, path)
        if not os.path.isfile(p):
            return False
        try:
            with open(p, errors="ignore") as f:
                return needle in f.read()
        except OSError:
            return False

    wf = os.path.join(repo, ".github", "workflows")
    ci_files = sorted(os.listdir(wf)) if os.path.isdir(wf) else []
    ci_text = ""
    for f in ci_files:
        try:
            with open(os.path.join(wf, f), errors="ignore") as fh:
                ci_text += fh.read()
        except OSError:
            pass

    return {
        "stack": detect_stack(repo),
        "hooks": os.path.isdir(os.path.join(repo, ".githooks")),
        # resumefit got here first, in bash; wealth-weave scans in CI.
        "house_gates": has_file("tools/check_hygiene.py",
                                "scripts/check-hygiene.sh"),
        "entry_point": has_file("Makefile", "justfile", "Taskfile.yml"),
        "constitution": has_file("CONSTITUTION.md", "specs/constitution.md"),
        "contributing": has_file("CONTRIBUTING.md"),
        "specs": os.path.isdir(os.path.join(repo, "specs")),
        # cloudsweep patched its vendored copy to name its own checker; a name the
        # skill does not know makes a complete repo audit as "missing".
        "spec_checker": has_file("tools/check_specs.py",
                                 "tools/check_clause_coverage.py",
                                 "tools/validate_contracts.py",
                                 "scripts/check-spec.sh"),
        "lint": (grep("pyproject.toml", "[tool.ruff]")
                 or grep("package.json", "eslint")
                 or has_file("ruff.toml", ".ruff.toml", ".eslintrc",
                             ".eslintrc.json", ".eslintrc.cjs",
                             "eslint.config.js", "eslint.config.mjs")),
        "types": (grep("pyproject.toml", "[tool.mypy]")
                  or grep("package.json", "typescript")
                  or has_file("tsconfig.json", "mypy.ini", ".mypy.ini")),
        "secret_scan": ("gitleaks" in ci_text
                        or has_file("tools/check_hygiene.py",
                                    "scripts/check-hygiene.sh")),
        "ci": bool(ci_files),
    }


ORDER = [("hooks", "local git hooks"),
         ("house_gates", "staged-content hygiene gate"),
         ("entry_point", "one-command entry point"),
         ("specs", "specs/"),
         ("spec_checker", "spec checker"),
         ("constitution", "constitution"),
         ("contributing", "CONTRIBUTING.md"),
         ("lint", "linter"),
         ("types", "type checker"),
         ("secret_scan", "secret scanning"),
         ("ci", "CI")]


# ---------------------------------------------------------------- install

# Appended inside every managed hook block, AFTER the house-gates check (which
# needs git's environment to see the index being committed) and BEFORE any project
# line below the block. git exports GIT_DIR, GIT_INDEX_FILE, … to hooks, absolute
# from a linked worktree, so a test fixture's `git init` in a temp dir acted on the
# real repository: keepsake 2026-11-07 (checkout turned bare, origin/main moved,
# junk branch pushed) and resumefit 2026-09-26. `git rev-parse --local-env-vars`
# is git's own list of the variables that pin a command to one repository.
SCRUB = '''# Scrub git's repository-local environment before any project command below.
# The index being committed stays reachable as HOUSE_GATES_INDEX_FILE for a
# staged-content check that needs it (`git commit <paths>` uses a temporary one).
if [ -n "${{GIT_INDEX_FILE:-}}" ]; then
  case "$GIT_INDEX_FILE" in
    /*) HOUSE_GATES_INDEX_FILE="$GIT_INDEX_FILE" ;;
    *)  HOUSE_GATES_INDEX_FILE="$PWD/$GIT_INDEX_FILE" ;;
  esac
  export HOUSE_GATES_INDEX_FILE
fi
cd "$root" || exit 1
for _house_gates_var in $(git rev-parse --local-env-vars); do unset "$_house_gates_var"; done
unset _house_gates_var
'''

PRE_COMMIT = '''#!/usr/bin/env bash
# {marker} v{version} — managed by the house-gates skill; re-run its
# installer to update. Local edits below the marker block are preserved.
#
# Staged content only, so committing stays near-instant. A slow pre-commit hook
# gets bypassed habitually, which is worse than no hook.
set -uo pipefail
root="$(git rev-parse --show-toplevel)"
if [ "${{HOUSE_GATES_SKIP:-}}" = "1" ]; then
  echo "pre-commit: SKIPPED via HOUSE_GATES_SKIP=1"
else
  "${{PYTHON:-python3}}" "$root/tools/check_hygiene.py" --hygiene || exit 1
fi
''' + SCRUB + '''# end {marker}
'''

# Written only into a pre-push hook the repo already has: house-gates has no push
# check of its own, but every pre-push here runs a test suite, which is exactly
# where an inherited GIT_DIR does its damage.
PRE_PUSH = '''#!/usr/bin/env bash
# {marker} v{version} — managed by the house-gates skill; re-run its
# installer to update. The repo's own pre-push lines follow the marker block.
root="$(git rev-parse --show-toplevel)"
''' + SCRUB + '''# end {marker}
'''

COMMIT_MSG = '''#!/usr/bin/env bash
# {marker} v{version} — managed by the house-gates skill.
set -uo pipefail
root="$(git rev-parse --show-toplevel)"
[ "${{HOUSE_GATES_SKIP:-}}" = "1" ] && exit 0
"${{PYTHON:-python3}}" "$root/tools/check_hygiene.py" --message "$1" || exit 1
# end {marker}
'''


def suggest_config(repo):
    """A starter config that fits how this repo already works.

    A gate calibrated against a repo's real history gets kept; one calibrated
    against an ideal gets switched off in week one. So: if a repo routinely
    commits large files, the size gate starts disabled rather than blocking the
    next legitimate commit — and says so in the file.
    """
    cfg = dict(DEFAULTS)
    sizes = []
    for path in git("ls-files", repo=repo).split("\n"):
        if not path.strip():
            continue
        full = os.path.join(repo, path)
        with contextlib.suppress(OSError):
            sizes.append(os.path.getsize(full))
    big = [s for s in sizes if s > DEFAULTS["max_bytes"]]
    if big:
        cfg["max_bytes"] = 0
        cfg["_note_max_bytes"] = (
            f"size gate off: this repo already tracks {len(big)} file(s) over "
            f"512 KB (largest {max(big) / 1048576:.1f} MB). Set a byte limit to "
            f"enable it.")
    # Name the branch this repo actually uses: suggesting "main" to a repo on
    # "master" produces a config that looks enabled and quietly does nothing.
    head = git("rev-parse", "--abbrev-ref", "HEAD", repo=repo).strip() or "main"
    default = head if head in ("main", "master") else "main"
    tracked = git("ls-files", repo=repo).split("\n")
    if any(f.endswith(".py") for f in tracked):
        cfg["determinism"] = True
    if any("migrations/" in f and f.endswith(".sql") for f in tracked):
        cfg["migrations"] = True
    # Only where the repo isn't already full of them — same logic as max_bytes.
    if not any(f.endswith(GENERATED) for f in tracked):
        cfg["artifacts"] = True
    if os.path.isdir(os.path.join(repo, ".github", "workflows")):
        cfg["workflows"] = True

    cfg["_note_protected_branches"] = (
        f'empty means the branch gate is OFF. Set ["{default}"] to require a '
        "branch per change, as resumefit does.")
    return cfg


def repo_private(repo):
    """The GitHub repository's visibility: True, False, or None when `gh` cannot
    say (not installed, not signed in, no GitHub remote). Never a guess."""
    try:
        out = subprocess.run(["gh", "repo", "view", "--json", "isPrivate",
                              "-q", ".isPrivate"], cwd=repo, capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    answer = out.stdout.strip().lower()
    if out.returncode or answer not in ("true", "false"):
        return None
    return answer == "true"


def _ensure_gitignored(repo, entry):
    path = os.path.join(repo, ".gitignore")
    text = ""
    if os.path.exists(path):
        with open(path) as f:
            text = f.read()
    if entry in (ln.strip() for ln in text.split("\n")):
        return False
    with open(path, "a") as f:
        if text and not text.endswith("\n"):
            f.write("\n")
        f.write(f"# personal values the house-gates hook refuses to commit; never tracked\n"
                f"{entry}\n")
    return True


def install(repo):
    """Write the hooks and vendor this file. Returns a list of what changed."""
    changed = []
    cfg_path = os.path.join(repo, CONFIG)
    private = repo_private(repo)
    if not os.path.exists(cfg_path):
        cfg = suggest_config(repo)
        cfg.pop("private", None)
        if private is not None:
            cfg["private"] = private
        else:
            cfg["_note_private"] = ("visibility unknown (`gh repo view` could not say); "
                                    "the hosted-runner check is skipped until \"private\" "
                                    "is set")
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        changed.append(CONFIG)
    elif private is not None:
        # Existing configs gain the key once; a known answer is never erased by a
        # later run where `gh` cannot reach GitHub.
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = None
        if isinstance(cfg, dict) and cfg.get("private") is None:
            cfg["private"] = private
            cfg.pop("_note_private", None)
            with open(cfg_path, "w") as f:
                json.dump(cfg, f, indent=2)
                f.write("\n")
            changed.append(f"{CONFIG} (private={str(private).lower()})")
    if _ensure_gitignored(repo, DENYLIST):
        changed.append(".gitignore")
    tools = os.path.join(repo, "tools")
    hooks = os.path.join(repo, ".githooks")
    os.makedirs(tools, exist_ok=True)
    os.makedirs(hooks, exist_ok=True)

    # CI runners only have the repository, never ~/.claude/skills — so the gate
    # is vendored, exactly as the spec-check skill does.
    with open(__file__) as f:
        me = f.read()
    dest = os.path.join(tools, "check_hygiene.py")
    old = ""
    if os.path.exists(dest):
        with open(dest) as f:
            old = f.read()
    if old != me:
        with open(dest, "w") as f:
            f.write(me)
        os.chmod(dest, 0o755)
        changed.append("tools/check_hygiene.py")

    for name, body in (("pre-commit", PRE_COMMIT), ("commit-msg", COMMIT_MSG),
                       ("pre-push", PRE_PUSH)):
        path = os.path.join(hooks, name)
        if name == "pre-push" and not os.path.exists(path):
            continue                    # only guards a suite the repo already runs
        text = body.format(marker=MARKER, version=VERSION)
        existing = ""
        if os.path.exists(path):
            with open(path) as f:
                existing = f.read()
        if f"# end {MARKER}" in existing:
            # Replace only our block, so a repo's own hook lines survive.
            end = existing.index(f"# end {MARKER}") + len(f"# end {MARKER}\n")
            text = text + existing[end:]
        elif existing:
            # Keep every line of the repo's hook; only its shebang is replaced by ours.
            rest = existing.split("\n", 1)[1] if existing.startswith("#!") else existing
            text = text + "\n" + rest
        if existing != text:
            with open(path, "w") as f:
                f.write(text)
            os.chmod(path, 0o755)
            changed.append(f".githooks/{name}")

    subprocess.run(["git", "-C", repo, "config", "core.hooksPath", ".githooks"],
                   capture_output=True)
    return changed


# ---------------------------------------------------------------- cli

def _report(problems, kind):
    if not problems:
        return 0
    print(f"\n{kind}: {len(problems)} problem(s)\n", file=sys.stderr)
    for item in problems:
        if isinstance(item, tuple):
            headline, advice, excerpt = item
            print(f"  blocked: {headline}", file=sys.stderr)
            if excerpt:
                print(f"           {excerpt}", file=sys.stderr)
            if advice:
                print(f"           {advice}", file=sys.stderr)
        else:
            print(f"  blocked: {item}", file=sys.stderr)
    print("\nTo bypass deliberately: HOUSE_GATES_SKIP=1 git commit …",
          file=sys.stderr)
    return 1


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    mode = argv[0]

    if mode == "--hygiene":
        return _report(hygiene("."), "hygiene")

    if mode == "--config":
        cfg = load_config(argv[1] if len(argv) > 1 else ".")
        for k, v in sorted(cfg.items()):
            if not k.startswith("_"):
                print(f"  {k:<20} {v}")
        return 0

    if mode == "--message":
        with open(argv[1]) as f:
            return _report(check_message(f.read()), "commit message")

    if mode == "--audit":
        repos = argv[1:] or ["."]
        width = max(len(os.path.basename(os.path.abspath(r))) for r in repos)
        for repo in repos:
            a = audit(repo)
            name = os.path.basename(os.path.abspath(repo))
            missing = [label for key, label in ORDER if not a[key]]
            print(f"{name:<{width}}  [{'+'.join(a['stack'])}]")
            if missing:
                print(f"{'':<{width}}  missing: {', '.join(missing)}")
            else:
                print(f"{'':<{width}}  complete")
        return 0

    if mode == "--ci-audit":
        rc = 0
        for repo in argv[1:] or ["."]:
            problems = ci_audit(repo)
            name = os.path.basename(os.path.abspath(repo))
            if problems:
                rc = 1
                print(f"{name}: {len(problems)} workflow problem(s)")
                for headline, _advice, _excerpt in problems:
                    print(f"  {headline}")
            else:
                print(f"{name}: workflows clean")
            for note in ci_audit_notes(repo):
                print(f"  note: {note}")
        return rc

    if mode == "--install":
        repo = argv[1] if len(argv) > 1 else "."
        changed = install(repo)
        name = os.path.basename(os.path.abspath(repo))
        if changed:
            print(f"{name}: installed — {', '.join(changed)}")
        else:
            print(f"{name}: already current (v{VERSION})")
        print(f"{name}: core.hooksPath set to .githooks")
        return 0

    print(f"unknown mode {mode!r}; see --help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
