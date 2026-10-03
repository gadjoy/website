# Implementation Plan: End-to-End Verification & Security Gates

**Spec**: [spec.md](spec.md) | **Date**: 2026-10-03

## Sequencing, and why

Security gates land **first**. They are cheap, they are pure CI configuration, and
CON-SEC-002's incident is that ten of twelve fleet projects scanned nothing for months
because the scanning was always the next thing. Entry-point checks come second for the same
reason — they are the highest ratio of defect-caught to effort in this list.

Playwright lands last because it is the only part with a real infrastructure cost, and
because its baselines are worth more once the pages they capture are not about to change.

## Phase A — Security gates (FR-009 … FR-012)

**pip-audit** over `migration/requirements.txt`, failing the build. `npm audit` is not
applicable: there is no `package.json` in this repo, which is itself worth asserting so the
gate does not silently pass by scanning nothing (CON-VER-005 — "could not determine" must
not read as "clean").

**gitleaks** over the **full history** (`--log-opts=--all`), not the diff. This repo carried
a `.wpress` backup and 15,554 `wp-export` files; a diff-only scan would have seen none of it.
Pinned by digest, not a floating tag.

**SECURITY.md** stating the posture, including the GitHub Pages header constraint. The
accompanying test reads the live site and asserts the document matches reality — so the
document cannot drift into fiction, which is the failure CON-SEC-004 actually names.

The shipped-vs-build split (FR-011) is a reporting shape, not a tool: `public/` is static
HTML with no bundled dependencies, so the honest report is "shipped tree carries no
third-party executable code; the entire dependency surface is build-time, executing with
credentials in CI." That is CON-SEC-003's point — the build tree is where the real risk is,
and it must not be dismissed.

## Phase B — Entry points (FR-006 … FR-008)

A table-driven test over every `*.py` in `tools/` and `migration/scripts/` that has a
`main()` or an `if __name__` guard. `--help` must exit 0. Exclusions are listed **in the
test, with a reason each**, never by silently narrowing the glob.

`--dry-run` is asserted by hashing the working tree before and after. The hash must be of
file *contents*, not mtimes, or the assertion passes for the wrong reason.

`smoke.sh` gets a fixture server: a page that is deliberately broken must make it exit
non-zero. Asserting only the success path would leave the smoke test free to stop checking
anything, which is the `| grep -q` under `pipefail` defect from house-gates 1.5.0.

## Phase C — Playwright (FR-001 … FR-005)

Chromium **directly on the runner**, no container, copying trailward's shape rather than
inventing one. `~/.cache/ms-playwright` cached on the lockfile hash. The runner is
GitHub-hosted: this repo is public, so minutes are free and the fleet's self-hosted rule
(which exists for billed private-repo minutes) does not apply.

Baselines are generated **on CI**, not locally: font rendering differs between this box
(Ubuntu 20.04) and the hosted runner (24.04), and a baseline captured in the wrong place
produces a gate that is permanently skipped or permanently red — either way, ignored
(CON-VER-004).

Comparison uses a pixel threshold tuned so antialiasing passes and a 10px element move fails.
Both directions are asserted (SC-002 and SC-003) — a threshold proven only in the passing
direction is a threshold that might be infinity.

## Phase D — Suite integrity (FR-013)

A second CI matrix leg with a different `PYTHONHASHSEED`. resumefit's two-seed matrix is the
in-house precedent, so this copies it rather than inventing a variant.

## Risks

- **Flaky visual diffs are the standard failure of this approach.** If the diff proves noisy
  in practice, the answer is a stricter mask or a named quarantine (CON-VER-008), never
  re-running until green.
- **Baseline churn.** Phases 2–5 of the working plan will rewrite most pages. Accepted: the
  baselines captured here are the "before" half of the Phase 6 comparison, which is their
  second purpose.
- **gitleaks on full history is slow** on a repo this size. Measured before it becomes a
  per-PR gate; if slow, it runs nightly plus on `main` rather than blocking every PR.
