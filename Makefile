PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
UVICORN := .venv/bin/uvicorn

.PHONY: help venv install test test-integration run db-up db-down db-migrate

help:
	@echo "Available targets:"
	@echo "  make venv      Create local virtualenv"
	@echo "  make install   Install project + dev dependencies"
	@echo "  make test      Run full test suite (single XML + HTML report)"
	@echo "  make test-integration  Run only Postgres integration tests"
	@echo "  make run       Run API locally on 127.0.0.1:8080"
	@echo "  make frontend-install  Install frontend dependencies"
	@echo "  make frontend-dev      Run frontend dev server on 127.0.0.1:5173"
	@echo "  make frontend-test     Run frontend Vitest suite"
	@echo "  make db-up     Start Postgres via Docker Compose"
	@echo "  make db-down   Stop Docker Compose services"
	@echo "  make db-migrate Apply SQL migrations to configured DB"

venv:
	python -m venv .venv

install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST) --junitxml=test-results/pytest.xml --html=test-results/pytest.html --self-contained-html

test-integration:
	TALLYBADGER_TEST_DATABASE_URL=$${TALLYBADGER_TEST_DATABASE_URL:-postgresql://tallybadger:tallybadger@127.0.0.1:5432/tallybadger} $(PYTEST) -m integration --junitxml=test-results/pytest.xml --html=test-results/pytest.html --self-contained-html

run:
	$(UVICORN) tallybadger.main:app --reload --host 127.0.0.1 --port 8080

frontend-install:
	npm --prefix frontend install

frontend-dev:
	npm --prefix frontend run dev

frontend-test:
	npm --prefix frontend test
	$(PYTHON) scripts/junit_to_html.py --xml test-results/frontend-vitest.xml --html test-results/frontend-vitest.html --title "TallyBadger Frontend Tests"

db-up:
	docker compose up -d db

db-down:
	docker compose down

db-migrate:
	PYTHONPATH=src $(PYTHON) -m tallybadger.db_migrations
