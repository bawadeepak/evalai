SHELL := /bin/bash
UV ?= uv
NPM ?= npm
PY := $(UV) run --frozen
FRONTEND := frontend

.PHONY: setup migrate demo dev test test-e2e build start lint clean-data

setup:  ## install locked Python and frontend dependencies
	$(UV) sync --frozen --python 3.12
	cd $(FRONTEND) && $(NPM) ci --no-audit --no-fund
	cd $(FRONTEND) && npx playwright install chromium

migrate:  ## migrate local database
	$(PY) evalai migrate

demo:  ## seed clearly labelled demo project, idempotently
	$(PY) evalai demo

dev:  ## start API (reload), worker and Vite dev UI with clean shutdown
	@trap 'kill 0' INT TERM EXIT; \
	$(PY) evalai migrate && \
	($(PY) evalai serve --reload &) && \
	($(PY) evalai worker &) && \
	(cd $(FRONTEND) && $(NPM) run dev &) && \
	wait

test:  ## unit + integration, no paid provider calls
	$(PY) pytest
	cd $(FRONTEND) && $(NPM) run test

test-e2e:  ## browser journeys against isolated data
	cd $(FRONTEND) && $(NPM) run build && npx playwright test

build:  ## type check and compile frontend/backend package
	$(PY) python -m compileall -q backend/eval_triage
	$(PY) ruff check backend tests
	cd $(FRONTEND) && $(NPM) run build

start:  ## serve built local application + worker
	$(PY) evalai start

lint:
	$(PY) ruff check backend tests

clean-data:  ## remove the local data directory (asks first)
	@read -p "Delete .data/ (all local evaluation data)? [y/N] " ans; [ "$$ans" = y ] && rm -rf .data || echo "kept"
