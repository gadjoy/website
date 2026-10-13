# Tasks: End-to-End Verification & Security Gates

> **Status: in progress.** Phases A and B are complete; every box below was ticked only
> after its guard had been mutated and seen to fail (CON-PROC-005). Phases C and D are
> outstanding and listed rather than omitted — an unchecked box here is a claim that work
> remains, not an oversight.
>
> Phase A turned up an unresolved credential exposure. It is recorded in `SECURITY.md`
> under **OPEN FINDING**, and rotating the key is an owner action that no test can close.

## Phase A — Security gates

- [x] A-1 `pip-audit` over `migration/requirements.txt` as a failing CI gate (FR-009)
- [x] A-2 Assert the dependency gate actually scans something, rather than passing vacuously
- [x] A-3 `gitleaks` over the full history, pinned by digest (FR-010)
- [x] A-4 `SECURITY.md` recording the posture and the Pages header constraint (FR-012)
- [x] A-5 Test asserting `SECURITY.md`'s claims match the live response (SC-011)
- [x] A-6 Shipped-tree vs build-tree audit written down (FR-011)

## Phase B — Entry points

- [x] B-1 Table-driven `--help` check over every entry point (FR-006, SC-006)
- [x] B-2 `--dry-run` leaves the tree byte-identical (FR-007, SC-007)
- [x] B-3 `smoke.sh` self-test against a fixture server (FR-008, SC-008)

## Phase C — Playwright

- [ ] C-1 Playwright + Chromium on the self-hosted runner, cached (FR-001)
- [ ] C-2 Journey test: homepage → repair post → contact (FR-002, SC-001)
- [ ] C-3 Screenshots at 1440px and 390px, baselines committed (FR-003, SC-004)
- [ ] C-4 Form submit path asserted against an intercepted request (FR-004, SC-005)
- [ ] C-5 Threshold proven in both directions (FR-005, SC-002, SC-003)

## Phase D — Suite integrity

- [ ] D-1 Second `PYTHONHASHSEED` matrix leg (FR-013, SC-012)

## Deferred

Nothing is deferred. Phases C and D are sequenced after A and B per the plan, not dropped.

## Found while doing this, not planned

- [x] `.env` untracked — it was committed before `.gitignore` listed it, and `.gitignore`
      does not untrack an existing file
- [x] `.gitleaks.toml` written because **stock gitleaks finds nothing** in that `.env`
- [ ] **Rotate the exposed OpenAI key** — owner action
- [ ] Decide whether to purge the values from history (rewrites 86 commits, 2.99 GiB pack,
      invalidates every clone) — owner decision, recorded in `SECURITY.md`
