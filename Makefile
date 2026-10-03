INTAKE ?= gadjoy/repairs-intake
VENV   ?= migration/.venv
PY     ?= $(VENV)/bin/python

.PHONY: help publish publish-dry test test-quick serve smoke venv sync merge canary freshness

help:
	@echo "make publish      publish pending repair decks from $(INTAKE), then commit+push a branch"
	@echo "make publish-dry  parse the pending decks and report; writes nothing"
	@echo "make test         run the acceptance gate + coverage floor (the same gate CI runs)"
	@echo "make test-quick   the same suite without the coverage floor, for fast iteration"
	@echo "make serve        hugo server with drafts"
	@echo "make smoke        smoke-test the live site"
	@echo "make venv         create migration/.venv and install requirements"
	@echo "make merge PR=n   merge a PR, but only once its checks are actually green"
	@echo "make canary       run the nightly checks by hand (suite + smoke + freshness)"

venv:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet -r migration/requirements.txt
	@echo "note: the customer-PII gate also needs the tesseract binary"
	@echo "      Debian/Ubuntu: sudo apt-get install tesseract-ocr   macOS: brew install tesseract"

# Publish the week's decks WITHOUT any new credential: uses the GitHub CLI login you
# already have. This is the route that needs no INTAKE_TOKEN — the Actions workflow is
# a convenience on top, not a prerequisite.
publish-dry:
	INTAKE_TOKEN=$$(gh auth token) OMP_THREAD_LIMIT=1 \
		$(PY) tools/publish_decks.py --from-intake $(INTAKE) --dry-run

publish:
	INTAKE_TOKEN=$$(gh auth token) OMP_THREAD_LIMIT=1 \
		$(PY) tools/publish_decks.py --from-intake $(INTAKE) --notify
	@if [ -n "$$(git status --porcelain content static)" ]; then \
		branch="content/decks-$$(date -u +%Y%m%d-%H%M)"; \
		git checkout -b "$$branch"; \
		OMP_THREAD_LIMIT=1 $(PY) migration/scripts/build_reviewed_manifest.py; \
		git add content static migration/tests/data; \
		git commit -m "Publish repair decks"; \
		git push -u origin "$$branch"; \
		gh pr create --base main --head "$$branch" --fill; \
		echo; echo "PR opened. Gates run on it; merge when green."; \
	else \
		echo "nothing new to publish"; \
	fi

# Branch protection is not enabled, so nothing server-side stops a merge landing before its
# checks finish — which has already happened twice here (#19, #21). This refuses.
merge:
	@test -n "$(PR)" || { echo "usage: make merge PR=<number>"; exit 2; }
	$(PY) tools/merge_guard.py $(PR) --wait

freshness:
	$(PY) tools/deploy_freshness.py --repo gadjoy/website

canary:
	@$(MAKE) test  || echo "SUITE FAILED"
	@$(MAKE) smoke || echo "SMOKE FAILED"
	@$(MAKE) freshness || echo "DEPLOY STALE"

# COVERAGE_MIN only ever ratchets UP (CON-COV-002). Target is 95% on gadjoy's own
# live code; raise this as tests land, never lower it to make a red build green.
#
# The baseline is measured on the interpreter CI actually runs (CON-VER-004), which
# is Python 3.13 via setup-python in hugo.yml. This is not pedantry — the same suite,
# same .coveragerc, measured 2026-10-02:
#
#     Python 3.13  ->  49.28%   (1034 stmts, 354 branches)   <- CI, authoritative
#     Python 3.8   ->  50.41%   (1032 stmts, 448 branches)   <- this VM's `make venv`
#
# 3.13's compiler emits far fewer branch arcs, so the denominator differs by ~1.1pp.
# A floor set from a local 3.8 run would have gone red on its first CI run.
# `make venv` yields 3.8 here (Ubuntu 20.04), which reads HIGHER — so a local pass
# does not by itself prove CI passes; the floor below is what makes it safe.
COVERAGE_MIN ?= 49

test:
	cd migration && OMP_THREAD_LIMIT=1 ../$(PY) -m pytest -q \
		--cov=../tools --cov=scripts --cov-config=../.coveragerc \
		--cov-report=term-missing:skip-covered \
		--cov-fail-under=$(COVERAGE_MIN)

# Same suite without the gate, for fast iteration.
test-quick:
	cd migration && OMP_THREAD_LIMIT=1 ../$(PY) -m pytest -q

serve:
	hugo server -D

smoke:
	./scripts/smoke.sh https://gadjoy.in

# Author's local mirror (macOS paths); not used by CI or by anyone else.
sync:
	rsync -av --delete --progress --exclude='.git' --exclude='.venv' \
		/Users/Vivekanand.balakrishnan/per/projects/sites/gadjoy/ \
		/Users/Vivekanand.balakrishnan/per/gadjoy
