# TallyBadger

Double-entry accounting for a **small set of rental properties**: journals, chart of accounts, bank import, mortgages, depreciation, and reporting—without the bloat of generic small-business packages.

**Stack today:** Python 3.11+, [FastAPI](https://fastapi.tiangolo.com/), PostgreSQL, Docker Compose, and a React + TypeScript + Vite frontend under `frontend/`.

**Not built yet (honest inventory):** auth, bank CSV ingestion, MCP tools, and advanced frontend workflows beyond account management.

---

## Where things are now

| Area | Status |
|------|--------|
| API shell | FastAPI app with `/`, `/health`, OpenAPI at `/docs` when running |
| Config | `tallybadger.core.config.Settings` — `TALLYBADGER_DATABASE_URL` (see below) |
| Database | PostgreSQL in Compose; `sql/002_ledger_mvp.sql` adds accounts + journal tables |
| Tests | `pytest` + `TestClient` (health + ledger service/API tests) |
| Container | `Dockerfile` + `docker-compose.yml` (`api` + `db`) |
| Front end | React + TypeScript + Vite shell with account list/create page |

---

## Double-entry (what that actually means)

Every business event is recorded as a **balanced journal entry**: one or more lines debiting accounts and one or more lines crediting accounts, with **total debits = total credits** for that entry.

- **Accounts** are buckets (Cash, Accounts Receivable, Rental Income, Repairs Expense, Loan Payable, …).
- **A transaction** is not “one number in one place”—it is a **set of lines** that explain the economic story (e.g. rent earned but not yet received increases receivable and income together).

That invariant is what keeps the books internally consistent and makes reports (balance sheet, income statement) reconcile to each other.

---

## Accrual vs cash (and the “exchange of value” idea)

**Cash basis:** recognise revenue when cash is received and expenses when cash is paid.

**Accrual basis:** recognise **revenue when it is earned** (usually when you have delivered the good/service—e.g. the rental period passes or you invoice) and **expenses when they are incurred** (when you owe them or consume the benefit—not necessarily when you pay the bill).

So accrual is **not** only “money changed hands.” Often it is the opposite: you record rent **earned** for March even if the tenant pays on April 2, and you record a repair **when the work is done** even if you pay the tradie next month. Cash movements then appear as movements in **Cash** paired with **Receivable**, **Payable**, or similar—still in balanced journal entries.

TallyBadger is aimed at **accrual** semantics for the ledger, while still letting you **reconcile cash** (bank lines) against those accrual entries.

*(Tax rules in your jurisdiction may differ from pure GAAP-style accrual; the app should produce clear reports so you or your accountant can map to filings.)*

---

## Product direction (from your notes, consolidated)

- **Properties & units** as dimensions on transactions (which building, which tenant).
- **Assets & depreciation** schedules; **budgets** and cash-flow goals.
- **Debt:** mortgages and lines of credit as liabilities with interest/principal split where needed.
- **Bank import:** ingest downloaded transactions, match rules, learn patterns; **ambiguous rows stay uncategorised** until you confirm—good fit for later **MCP** helpers that suggest accounts but do not silently post money.
- **Reporting:** rent statements, year-end packs, export for tax prep—not legal advice, but structured data.

---

## Quick start (local)

```bash
cd /path/to/TallyBadger
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn tallybadger.main:app --reload --host 127.0.0.1 --port 8080

# apply migrations
tallybadger-migrate
# or
make db-migrate
```

- API: http://127.0.0.1:8080  
- Interactive docs: http://127.0.0.1:8080/docs  

Optional `.env` (or environment variables):

```bash
TALLYBADGER_DATABASE_URL=postgresql://tallybadger:tallybadger@127.0.0.1:5432/tallybadger
```

Run tests (single consolidated report):

```bash
pytest
# or
make test
```

Quick dev control targets:

```bash
make up           # start db + api + frontend in background
make status       # show service status
make logs         # show api/frontend logs
make down         # stop all services
```

Equivalent direct CLI (no environment argument):

```bash
PYTHONPATH=src .venv/bin/python -m tallybadger.tbad up
PYTHONPATH=src .venv/bin/python -m tallybadger.tbad status
PYTHONPATH=src .venv/bin/python -m tallybadger.tbad logs api
PYTHONPATH=src .venv/bin/python -m tallybadger.tbad down
```

Run frontend tests:

```bash
make frontend-install
make frontend-test
```

Frontend test report location:

- `test-results/frontend-vitest.html` (static HTML; open directly in browser)

Test report locations:

- `test-results/pytest.xml`
- `test-results/pytest.html` (open in browser)

Run integration tests against a live PostgreSQL instance:

```bash
make db-up
make db-migrate
TALLYBADGER_TEST_DATABASE_URL=postgresql://tallybadger:tallybadger@127.0.0.1:5432/tallybadger make test
```

---

## Docker

```bash
docker compose up --build
```

- API: http://127.0.0.1:8080  
- Postgres: `localhost:5432`, user/db/password `tallybadger` (change for real deployments).

---

## Frontend

```bash
make frontend-install
make frontend-dev
```

- UI: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8080`

Use `VITE_API_BASE_URL` when the API host/port differs from local defaults.

When started via `make up`, service logs are written to `local/logs/` and pid files to `local/run/`.

---

## Repository layout

```
├── pyproject.toml          # Dependencies & packaging
├── src/tallybadger/        # Application code
│   ├── main.py             # FastAPI app factory wiring
│   ├── api/routes/         # HTTP routers
│   └── core/               # Settings, shared utilities
├── tests/                  # Pytest
├── sql/                    # SQL migrations / reference DDL
├── frontend/               # React + TypeScript + Vite UI
├── Dockerfile
└── docker-compose.yml
```

---

## Money in code (non-negotiable)

Use **decimal types** (e.g. Python `Decimal` or integer minor units), not binary floats, for currency amounts.

---

## Backup and recovery

- **Database:** regular `pg_dump` (logical) or filesystem snapshots of the Postgres data volume. For Compose, the named volume `pgdata` holds data; back it up with your host backup strategy or dump from the container.
- **Application:** configuration and SQL migrations live in git; secrets do not.

---

## Kubernetes

Compose is the reference for a single host (e.g. a Celeron box with 16 GB RAM). For Kubernetes: run the same API image, managed Postgres (or a StatefulSet), inject `TALLYBADGER_DATABASE_URL` via secrets, and front with an Ingress. No K8s manifests ship in-repo yet.

---

## Working style

Stakeholder steers; implementation and dependencies are handled in-repo (`pyproject.toml`, `pip install -e ".[dev]"`). When something new is needed, it gets declared in `pyproject.toml` and installed like any other Python project—no hand-wavy “install this random CPAN module” detours.
