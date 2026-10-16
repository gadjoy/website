# Security posture — gadjoy.in

Spec [012](specs/012-e2e-and-security-gates/). Satisfies CON-SEC-002, CON-SEC-003 and
CON-SEC-004 of the shared engineering constitution.

This file is asserted against reality by `migration/tests/test_security_posture.py`. If a
claim here stops being true, that test fails — a posture document nobody checks becomes
fiction, which is the failure CON-SEC-004 is about.

---

## RESOLVED BY OWNER DECISION — credentials in git history

**Found 2026-10-03** while building the secret-scanning gate. **Closed 2026-10-16** by the
repository owner's assessment, recorded here rather than deleted.

This repository is **public** (created 2025-05-30). `.env` was committed in `92157832` on
**2025-06-04** and remained tracked in `HEAD` until 2026-10-03 — roughly **sixteen months
world-readable**. `.gitignore` had listed `.env` since line 13, but `.gitignore` does not
untrack a file that is already tracked, so the rule never took effect.

| Variable | Disposition |
|---|---|
| `OPENAI_API_KEY` | 164-character `sk-` project key. **Owner assessed it as no longer active (2026-10-16); no rotation performed.** |
| `MYSQL_ROOT_PASSWORD` | Local Docker WordPress stack, never reachable off-host |
| `WP_DB_PASSWORD` | Local Docker WordPress stack, never reachable off-host |

**What was actually done, stated precisely:** `.env` was untracked, and GitHub secret
scanning and push protection were enabled. The key was **not** rotated and the history was
**not** purged — the owner judged the credential inactive. That is a decision, not a
verification: this document does not claim the key was revoked, because nobody checked.
The values remain readable in history to anyone.

Recorded rather than removed because a finding that disappears leaves no trace of whether
it was fixed or forgotten (CON-DATA-001: the distinction is the information).

### Why nothing caught it for sixteen months

GitHub's own secret scanning was **disabled** on this repository, as were push protection
and Dependabot security updates — all free for public repos.

And `gitleaks` 8.21.2 with **stock rules reports "no leaks found"** against that exact
file: its `sk-` rule does not match project-scoped keys, which contain `-` and `_`. GitHub's
scanner flagged it within seconds of being switched on.

Both now run. `.gitleaks.toml` carries custom rules for the gap, and the platform scanner
provides an independent second opinion — a single scanner is a single point of failure, and
the free one was off.

## Response headers

**GitHub Pages cannot set response headers.** There is no configuration — no `_headers`
file, no `netlify.toml` equivalent, no edge worker. This is a platform limitation, recorded
rather than left silent (CON-SEC-004 names silence as the failure, not the absence).

| Header | Served | Note |
|---|---|---|
| `Content-Security-Policy` | **no** | Not settable on Pages. A `<meta http-equiv>` CSP is possible but cannot carry `frame-ancestors` or `report-uri`, and would break the theme's inline scripts. Not adopted; reconsider if the site moves to a host that can set headers. |
| `Strict-Transport-Security` | **yes** | Set by GitHub Pages itself for `*.github.io`; on the custom domain it depends on the Pages TLS setting ("Enforce HTTPS"). |
| `X-Content-Type-Options` | **no** | Not settable. |
| `Referrer-Policy` | **no** | Not settable. A `<meta name="referrer">` equivalent is available and is the one mitigation worth taking if referrer leakage becomes a concern. |
| `X-Frame-Options` | **no** | Not settable. |

**What the platform does allow, and what is therefore relied on:** HTTPS with an
auto-provisioned certificate, HSTS when "Enforce HTTPS" is on, and the fact that the site is
wholly static — no server-side execution, no database, no session, no authentication. The
attack surface a CSP would normally reduce is correspondingly small: the only third-party
origins the pages talk to are the form endpoint and, when enabled, the analytics and
Google Maps embeds.

## Shipped tree vs build tree (CON-SEC-003)

Reported separately, because a single number misleads.

**Shipped tree (`public/`)** — static HTML, CSS, images and the theme's JavaScript. It carries
**no third-party executable dependency**: there is no `package.json` in this repository and
nothing is bundled at build time. The JavaScript that ships is the vendored theme's own,
pinned at the commit recorded in `themes/`.

**Build tree** — `migration/requirements.txt` (the test and migration toolchain), the pinned
Hugo binary, and the GitHub Actions workflows. **This is where the entire real risk lives.**
It executes in CI with a `GITHUB_TOKEN` and, for the deck pipeline, an `INTAKE_TOKEN`. A
compromised build-time dependency could alter what is published.

That asymmetry is the point of CON-SEC-003: a build-tree advisory must never be waved away
as "not shipped" here, because the build tree is the privileged one.

## Dependency advisories — and why the number depends on the interpreter

Measured 2026-10-03 against `migration/requirements.txt`, which pins only lower bounds:

| Interpreter | Result | Where it is used |
|---|---|---|
| **Python 3.13** | **No known vulnerabilities** | CI, and therefore everything that builds and deploys |
| Python 3.8 | 31 advisories across pillow, urllib3, requests, pytest, soupsieve | `make venv` on the Ubuntu 20.04 dev box only |

Both numbers are true, and reporting only one would mislead (CON-VER-005). The 3.8 figure
is **not** 31 vulnerable dependencies in this project — it is the resolver being unable to
install current releases on an interpreter they no longer support. Pillow 12.x and
urllib3 2.5+ require Python 3.9 or newer.

Nothing vulnerable ships either way: `public/` contains no Python. The 3.8 exposure is real
but narrow — it executes only when a developer runs the suite locally on that box. **The
durable fix is to stop using Python 3.8 for local development**, not to pin the
requirements downward, which would make CI worse to make a local number smaller.

The gate runs on 3.13 because that is the interpreter that actually builds and deploys
(CON-VER-004). A gate run against an environment nothing ships from would be measuring the
wrong thing.

## The 70 Dependabot alerts, traced (CON-SEC-003)

GitHub reports **70 open alerts on the default branch — 14 critical, 30 high, 17 moderate,
9 low** — while `pip-audit` reports none. Both are correct, and the gap is the whole point
of CON-SEC-003: a tool's own split is not a trace.

**Every one of the 70 is in `migration/wp-export/wp-content/themes/twenty*/package-lock.json`**
— the npm *build* dependencies of WordPress's default themes, captured wholesale in the
content export.

| Manifest | Alerts |
|---|---|
| `…/themes/twentytwenty/package-lock.json` | 45 |
| `…/themes/twentynineteen/package-lock.json` | 17 |
| `…/themes/twentytwentyone/package-lock.json` | 8 |

Traced, not assumed:

- There is **no `package.json` or lockfile at the repository root**, so CI's
  `[[ -f package-lock.json ]] && npm ci || true` step is a guarded no-op. Nothing is ever
  installed from those lockfiles.
- **Nothing in `layouts/`, `static/`, `data/` or `hugo.yaml` references those themes.**
  Hugo's `theme:` is `hugo-universal-theme`.
- They are therefore neither shipped nor build-tree: they are inert files in a content dump,
  with no execution path at all.

This is the portfolio precedent repeating — 26 advisories there traced to zero real ones.
And the inverse warning still applies: this is **not** a licence to wave away a build-tree
advisory as "not shipped". It is a trace showing these particular files are in neither tree.

**The honest fix is to delete the vendored WordPress themes.** Principle II already says
`migration/wp-export/` is not a source, and nothing reads them. That would retire all 70
alerts rather than annotating them. It is proposed, not done, because deleting part of the
content export is the owner's call.

## Gates

| Gate | Runs | Fails the build |
|---|---|---|
| `pip-audit` over `migration/requirements.txt` | every PR and push | yes, on any known advisory |
| `gitleaks` over the working tree | every PR and push | yes |
| `gitleaks` over **full history** | nightly | yes, and opens an issue |
| GitHub secret scanning | continuous, platform-side | alerts; independent of CI |
| GitHub push protection | on every push | yes — blocks the push |
| Coverage floor (95%) | every PR and push | yes |

The full-history scan is nightly rather than per-PR because it takes **6m59s** on this
repository — measured, on a 2.99 GiB pack carrying a `.wpress` backup and 15,554
`wp-export` files. Blocking every PR on a seven-minute scan is how a gate gets bypassed.

Scan reports contain the secret values they find and are therefore **never** uploaded as
CI artifacts.

## Reporting a vulnerability

Email **vivek@gadjoy.in**. This is a small business's website; there is no bug bounty, and a
response may take a few days.
