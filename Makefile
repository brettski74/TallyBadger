PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
UVICORN := .venv/bin/uvicorn

.PHONY: help venv install test run db-up db-down

help:
	@echo "Available targets:"
	@echo "  make venv      Create local virtualenv"
	@echo "  make install   Install project + dev dependencies"
	@echo "  make test      Run pytest (writes XML + HTML reports)"
	@echo "  make run       Run API locally on 127.0.0.1:8080"
	@echo "  make db-up     Start Postgres via Docker Compose"
	@echo "  make db-down   Stop Docker Compose services"

venv:
	python -m venv .venv

install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST)

run:
	$(UVICORN) tallybadger.main:app --reload --host 127.0.0.1 --port 8080

db-up:
	docker compose up -d db

db-down:
	docker compose down
