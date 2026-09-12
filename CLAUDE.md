# Gadjoy — contributor & agent guide

> **Read [`.specify/memory/constitution.md`](.specify/memory/constitution.md) first.**
> **Ten** non-negotiables (v2.0.0) governing the site — not just the finished migration.
> Principle I exists because
> **the previous migration shipped with zero tests and silently corrupted 1,500+ posts** —
> these are not style preferences.

This file exists so the constitution actually reaches you: `CLAUDE.md` is loaded
automatically in every session, `.specify/memory/` is not. It replaces a Spec Kit
placeholder that said only "read the current plan" and never mentioned the constitution
sitting beside it.

Machine-wide engineering principles are in `~/.claude/CLAUDE.md` and apply here too.

## What this is

The website for **Gadjoy Repair Service**, a device-repair shop in Bangalore. Live at
<https://gadjoy.in/>. Hugo static site, deployed by the `hugo.yml` workflow.

It is a **real business's live site**. A broken build or a dead URL costs the shop
customers, which is why URL parity (Principle IV) is a tested invariant rather than a
hope.

## The ten, in one line each

1. **Test-First (non-negotiable)** — red → green → refactor. No extractor or conversion
   code before a failing test exists for it.
2. **Single source of truth** — content derives from the restored WordPress instance.
   `migration/wp-export/posts.json` and the existing broken `public/` HTML are **not**
   sources and must never be used to reconstruct content.
3. **No fabricated data** — taxonomy, dates, slugs and excerpts are read as stored.
   Guessing a category from a post title is forbidden. **Absent in the source means
   absent in the output.**
4. **Exact URL preservation** — every post reachable at its original URL, permalinks read
   from `wp_options.permalink_structure`, plus an `aliases:` entry as a safety net.
5. **Lossless, verifiable content** — no `<!-- wp: -->` comments, no `[shortcode]`
   residue; every image path canonical and the file present on disk.
6. **Reproducible source** — Markdown in `content/blog/`, regenerable by `hugo`. Content
   that exists only as built HTML is unacceptable.
7. **Every production bug becomes a test** — written first, confirmed red against the
   unfixed code. And a guard is only real once you have watched it fail: two guards
   shipped passing vacuously before being checked that way.
8. **Gates run in CI, not from memory** — `pytest` + a clean build are enforced on every
   PR. The suite was silently red on `main` for two months while PR bodies truthfully
   reported it green, because it had last been run on a case-insensitive filesystem.
9. **Verify the deployed site, not just the build** — `scripts/smoke.sh` after every
   deploy. A layout fallback and a dead contact form both returned HTTP 200 throughout.
10. **Public claims trace to a source** — every number on the site comes from `hugo.yaml`
   or another named source, never a template literal and never derived from something
   that merely correlates.

Principles II, III and X are the same rule this project keeps needing: **record what the
source says, never what you can infer.** A guessed category is indistinguishable from a
real one once written, and it is the guess you will publish. The homepage claimed "1508+
repairs" for months because the figure was *derived* — a real number measuring the wrong
thing.

**When a spec is required:** anything that adds or reshapes a user-facing capability, or
touches migration/test infrastructure. **Not** required for copy edits, CSS tweaks,
dependency bumps or single-file bug fixes — those go on `fix/` or `chore/` branches. The
branch prefix is the declaration, and CI fails a `feat/*` PR that touches no `specs/` file.

## Commands

```bash
make test            # the acceptance gate CI runs (~140 tests); needs tesseract for the PII gate
make serve           # hugo server with drafts
make smoke           # check the live site
make publish         # publish pending repair decks from the private intake repo
make venv            # create migration/.venv and install requirements
```

`migration/tests/` holds the migration invariants (`test_invariants.py`, `test_conversion.py`,
`test_golden.py`, `test_build.py`) plus the site-level gates added later: `test_site_output.py`
(built HTML), `test_no_device_identifiers.py` (customer PII in photos), `test_toolchain.py`
(dev/CI Hugo parity), `test_spec_hygiene.py`, `test_gate_scoping.py`, and the deck pipeline's
`test_deck_*.py`. Do not weaken an invariant to make a change pass — and if you must re-scope
one, ship a test proving it still catches the bug it was built for (see `test_gate_scoping.py`).

**Gate on exit codes, never on reading output** (CON-VER-001) — the constitution carries the rule and the incident behind it; what follows is how it bites here. A summary line can say "passed" while
the process exits non-zero.

## Layout

- `content/blog/` — migrated Markdown (the authoritative source)
- `migration/` — extractors, converters and the test suite
- `wordpress/backup/` — the `.wpress` backup everything derives from
- `specs/` — one directory per feature; `specs/README.md` is the index and the
  **Tests Owed** register
- `tools/` — the deck → posts publishing pipeline
- `.hugo-version` — the single source of truth for the Hugo version, read by CI
- `layouts/`, `themes/`, `static/`, `data/` — Hugo site
- `public/` — **build output; never a source**

## Workflow

Every change lands through a reviewed PR. New behaviour starts with a spec, then tests
derived from its acceptance criteria, then code — Principle I is explicit that the order
matters.

If you add a rule, add the check that catches its violation in the same change. A rule
with no enforcing mechanism is a wish, and this project already learned what an
unenforced "be careful" is worth: 1,500 corrupted posts.
