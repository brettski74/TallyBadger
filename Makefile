PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
UVICORN := .venv/bin/uvicorn

.PHONY: help venv install test test-unit test-integration run up down restart status logs frontend-install frontend-dev frontend-test db-up db-down db-wait db-migrate db-migrate-local dbempty dbclean dev-seed export-dev-seed export-bootstrap

help:
	@echo "Available targets:"
	@echo "  make venv      Create local virtualenv"
	@echo "  make install   Install project + dev dependencies"
	@echo "  make test      Run all pytest tests (db-up, migrate, then unit + integration); report: test-results/pytest.html"
	@echo "  make test-unit Run pytest excluding integration (no DB required); same report paths"
	@echo "  make test-integration  Run only integration tests; same report paths"
	@echo "  make run       Alias for make up"
	@echo "  make up        Start DB + API + frontend in background via tbad"
	@echo "  make down      Stop DB + API + frontend via tbad"
	@echo "  make restart   Restart DB + API + frontend via tbad"
	@echo "  make status    Show DB + API + frontend status via tbad"
	@echo "  make logs      Show API + frontend logs via tbad"
	@echo "  make frontend-install  Install frontend dependencies"
	@echo "  make frontend-dev      Run frontend dev server on 127.0.0.1:5173"
	@echo "  make frontend-test     Run frontend Vitest suite"
	@echo "  make db-up     Start Postgres via Docker Compose"
	@echo "  make db-down   Stop Docker Compose services"
	@echo "  make db-wait   Wait for Postgres readiness"
	@echo "  make db-migrate Apply SQL migrations to configured DB"
	@echo "  make dbempty   Recreate local DB volume and apply schema migrations only (no dev_seed; dev only)"
	@echo "  make dbclean   Same as dbempty, then load sql/dev_seed.sql (dev only)"
	@echo "  make dev-seed  Apply sql/dev_seed.sql (accounts, parties, CEL rule sets, templates — dev only)"
	@echo "  make export-dev-seed  Rewrite sql/dev_seed.sql from the current DB (commit for your team)"
	@echo "  make export-bootstrap  Alias for export-dev-seed"

venv:
	python -m venv .venv

install:
	$(PIP) install -e ".[dev]"

test: db-migrate-local
	TALLYBADGER_TEST_DATABASE_URL=$${TALLYBADGER_TEST_DATABASE_URL:-postgresql://tallybadger:tallybadger@127.0.0.1:5432/tallybadger} $(PYTEST) --junitxml=test-results/pytest.xml --html=test-results/pytest.html --self-contained-html

test-unit:
	$(PYTEST) -m "not integration" --junitxml=test-results/pytest.xml --html=test-results/pytest.html --self-contained-html

test-integration:
	TALLYBADGER_TEST_DATABASE_URL=$${TALLYBADGER_TEST_DATABASE_URL:-postgresql://tallybadger:tallybadger@127.0.0.1:5432/tallybadger} $(PYTEST) -m integration --junitxml=test-results/pytest.xml --html=test-results/pytest.html --self-contained-html

run: up

up: db-migrate-local
	PYTHONPATH=src $(PYTHON) -m tallybadger.tbad up

down:
	PYTHONPATH=src $(PYTHON) -m tallybadger.tbad down

restart:
	PYTHONPATH=src $(PYTHON) -m tallybadger.tbad restart

status:
	PYTHONPATH=src $(PYTHON) -m tallybadger.tbad status

logs:
	PYTHONPATH=src $(PYTHON) -m tallybadger.tbad logs

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

db-wait:
	@echo "Waiting for Postgres to accept connections..."
	@for i in $$(seq 1 30); do \
		if docker compose exec -T db pg_isready -U tallybadger -d tallybadger >/dev/null 2>&1; then \
			echo "Postgres is ready."; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Timed out waiting for Postgres readiness."; \
	exit 1

db-migrate-local: db-up db-wait
	PYTHONPATH=src $(PYTHON) -m tallybadger.db_migrations

db-migrate:
	PYTHONPATH=src $(PYTHON) -m tallybadger.db_migrations

dbempty:
	docker compose down -v
	docker compose up -d db
	$(MAKE) db-wait
	PYTHONPATH=src $(PYTHON) -m tallybadger.db_migrations

dbclean: dbempty
	$(MAKE) dev-seed

dev-seed:
	PYTHONPATH=src $(PYTHON) -m tallybadger.dev_seed apply

export-dev-seed:
	PYTHONPATH=src $(PYTHON) -m tallybadger.dev_seed export

export-bootstrap: export-dev-seed
