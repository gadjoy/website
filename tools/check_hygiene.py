#!/usr/bin/env python3
"""house_gates.py — the local gates every repo in this house should have.

Stdlib only, no install, works on any stack. Two things it does:

    house_gates.py --audit [REPO]     read-only: which gates exist, which don't
    house_gates.py --install REPO     write the hooks and vendor this file

and one thing it *is* — the gate itself, run by the pre-commit hook:

    house_gates.py --hygiene          check the staged content, block on failure
    house_gates.py --message FILE     check a commit message says why

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
"""
import json
import os
import re
import subprocess
import sys

VERSION = "1.1.0"
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
}

# ---------------------------------------------------------------- shell helpers


def git(*args, repo="."):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True).stdout


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
    r"<[a-z_ -]+>|\$\{?[A-Z_]+|os\.environ|process\.env|getenv|import\.meta\.env",
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


def scan_secrets(path, content):
    """Problems in one staged file. `hygiene-ok: <reason>` exempts the file."""
    if EXCEPTION.search(content):
        return []
    problems = []
    for pattern, what, advice in SECRET_PATTERNS:
        for line in content.split("\n"):
            if not pattern.search(line):
                continue
            if PLACEHOLDER.search(line):
                continue
            problems.append((f"{path} contains {what}.", advice,
                             line.strip()[:72]))
            break                      # one report per pattern is enough
    return problems


def check_protected_branch(repo=".", protected=()):
    if not protected:
        return []
    branch = git("rev-parse", "--abbrev-ref", "HEAD", repo=repo).strip()
    if branch in protected:
        return [(f"you are on '{branch}'. Work belongs on a branch.",
                 "git switch -c feat/my-change   # your staged work comes with you",
                 "")]
    return []


def check_size(path, repo=".", max_bytes=512 * 1024):
    if not max_bytes:
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


def hygiene(repo=".", cfg=None):
    """Every problem with the staged content. Empty means the commit may proceed."""
    cfg = cfg or load_config(repo)
    problems = list(check_protected_branch(repo, cfg["protected_branches"]))
    for path in staged_files(repo):
        problems += check_size(path, repo, cfg["max_bytes"])
        if is_probably_binary(path, repo):
            continue
        content = git("show", f":{path}", repo=repo)
        if content and cfg["secrets"]:
            problems += scan_secrets(path, content)
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
        "spec_checker": has_file("tools/check_specs.py",
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
# end {marker}
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
        try:
            sizes.append(os.path.getsize(full))
        except OSError:
            pass
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
    cfg["_note_protected_branches"] = (
        f'empty means the branch gate is OFF. Set ["{default}"] to require a '
        "branch per change, as resumefit does.")
    return cfg


def install(repo):
    """Write the hooks and vendor this file. Returns a list of what changed."""
    changed = []
    cfg_path = os.path.join(repo, CONFIG)
    if not os.path.exists(cfg_path):
        with open(cfg_path, "w") as f:
            json.dump(suggest_config(repo), f, indent=2)
            f.write("\n")
        changed.append(CONFIG)
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

    for name, body in (("pre-commit", PRE_COMMIT), ("commit-msg", COMMIT_MSG)):
        path = os.path.join(hooks, name)
        text = body.format(marker=MARKER, version=VERSION)
        existing = ""
        if os.path.exists(path):
            with open(path) as f:
                existing = f.read()
        if MARKER in existing:
            # Replace only our block, so a repo's own hook lines survive.
            start = existing.index("#!/usr/bin/env bash")
            end = existing.index(f"# end {MARKER}") + len(f"# end {MARKER}\n")
            text = text + existing[end:]
        elif existing:
            text = text + "\n" + existing.split("\n", 1)[1]
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
