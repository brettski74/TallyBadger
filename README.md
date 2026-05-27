# TallyBadger

Double-entry accounting for a **small set of rental properties**: journals, chart of accounts, bank import, mortgages, depreciation, and reporting—without the bloat of generic small-business packages.

**Stack today:** Python 3.11+, [FastAPI](https://fastapi.tiangolo.com/), PostgreSQL, Docker Compose, and a React + TypeScript + Vite frontend under `frontend/`.

**Where to read next:** **[ARCH.md](ARCH.md)** is the maintained map of subsystems, trust boundaries, and main data flows (including containers). **[STYLE.md](STYLE.md)** is how we code, test, and ship. This README stays **product- and operator-focused** (quick start, Docker, layout); it should not drift into duplicating ARCH/STYLE.

**Not built yet (honest inventory):** end-user **auth**, **MCP** helpers, and **simplified non-accountant** flows. **Bank CSV import** is **implemented and usable** today (upload → column mapping / templates → CEL rule sets where configured → journal posting via the API); rough edges and future work include **duplicate handling**, **cheque reconciliation**, and **tighter settlement / accrual integration** with that pipeline—not “CSV missing.” Settlements / accrual obligations ([#7](https://github.com/brettski74/TallyBadger/issues/7)) and **import rules** ([#8](https://github.com/brettski74/TallyBadger/issues/8)) are documented in **`docs/import-rules-engine.md`** (CEL-only path for CSV).

---

## Where things are now

| Area | Status |
|------|--------|
| API shell | FastAPI app with `/`, `/health`, OpenAPI at `/docs` when running |
| Config | `tallybadger.core.config.Settings` — `TALLYBADGER_DATABASE_URL` (see below); journal **attachment** max upload size lives on **`ledger_settings.max_attachment_upload_bytes`** (default **5 MiB**), adjustable via `PATCH /ledger-settings` using a byte integer or a string with **`k`** (×1024) or **`M`** (×1048576) |
| Database | PostgreSQL in Compose; `sql/*.sql` migrations (ledger, accruals, settlements, …) |
| Bank CSV import (#40 / #9) | Upload and execute path in API (`import_csv` routes); templates + CEL rule sets; posts journals — usable; gaps: duplicates, cheque reconciliation, settlement wiring |
| Import rules (#8) | **CEL** rules: **`evaluate_cel`**, persisted rule sets (`/import-rules/cel/rule-sets`), **`POST /import-rules/cel/evaluate`**, CSV execute with `cel_rule_set_id`; **Import rules** tab in the SPA for editing sets — **see [docs/import-rules-engine.md](docs/import-rules-engine.md)** |
| Backup / restore ([#67](https://github.com/brettski74/TallyBadger/issues/67)) | `POST /backup/export` and `POST /backup/import` (complete JSON ZIP); format: **[docs/backup-snapshot-format.md](docs/backup-snapshot-format.md)**; Configuration tab in the UI |
| Tests | `pytest` + `TestClient` (health, ledger, import rules, …); reports under `test-results/` |
| Container | `Dockerfile` + `docker-compose.yml` (`api` + `db`) |
| Front end | React + TypeScript + Vite: chart of accounts, journal entries, accrual plans, settlements |

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

Run tests — **single** backend report (`test-results/pytest.html` / `pytest.xml`; last command wins):

```bash
make test          # full suite: Docker DB + migrate + all tests (incl. integration)
make test-unit     # skip integration (no DB required)
make test-integration   # integration tests only (DB must be up / migrated)
```

See [docs/import-rules-engine.md](docs/import-rules-engine.md) for import rules behaviour (#8), including the CEL spike endpoint (`/import-rules/cel/evaluate`).

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

Backend test report (same paths for every target; last run wins):

- `test-results/pytest.xml`
- `test-results/pytest.html`

---

## Docker

```bash
docker compose up --build
```

- API: http://127.0.0.1:8080  
- Postgres: `localhost:5432`, user/db/password `tallybadger` (change for real deployments). Timezone is aligned in three places: the container clock (`TZ` and mounted `/etc/localtime`), persisted defaults on the `tallybadger` database and role (init script on first volume create; reapplied on every `make db-migrate` / `apply_sql_migrations`), and `SET TIME ZONE` on each app connection. Override with `TALLYBADGER_TIMEZONE`, `TALLYBADGER_IMPORT_TZ`, or `TZ` (see `tallybadger.core.timezone`).

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

### PostgreSQL (host-level)

- **Database:** regular `pg_dump` (logical) or filesystem snapshots of the Postgres data volume. For Compose, the named volume `pgdata` holds data; back it up with your host backup strategy or dump from the container.
- **Application code:** configuration and SQL migrations live in git; secrets do not.

### Application snapshot (ZIP)

TallyBadger can export and import ledger data as a **versioned ZIP** of JSON table dumps (see **[docs/backup-snapshot-format.md](docs/backup-snapshot-format.md)** for layout, `format_version`, and validation rules).

- **UI:** **Configuration** tab — export scope, restore mode (how to handle duplicate keys on import), download and file picker.
- **API:** `POST /backup/export?export_type=complete|configuration|financial` (response: ZIP), `POST /backup/import` with multipart field `snapshot` and form field `restore_mode` (`abort`, `overwrite`, `erase-reload`; prefixes allowed). OpenAPI: `/docs`.
- **CLI:** **`tbload`** (`scripts/tbload`, installed with the package) — thin `curl` wrapper for restore; default mode **`abort`**. Requires `curl` and Python 3.11+ on the host (not inside the API container). **`-i` / `--input`** accepts a **ZIP file** or an **expanded snapshot directory** (top-level `*.json` plus optional `attachments/`). The CLI only checks that **`metadata.json`** exists in a directory; manifest, SHA-256, and other validation run on the server. **Stdin accepts ZIP only** (not expanded directories).

Error responses use plain-English prefixes (integrity vs validation vs database constraint) so you can tell checksum/manifest issues apart from business-rule checks and PostgreSQL FK/unique failures.

#### Local restore drill (reviewers / operators)

Use a throwaway database (Compose default is fine). Example with API on `http://127.0.0.1:8080`:

1. **Seed or create data** you care about (use the UI, integration tests, or restore a snapshot).
2. **Export:** `curl -fsS -X POST -o /tmp/tb-snap.zip "http://127.0.0.1:8080/backup/export?export_type=complete"` (or copy into `examples/tallybadger-complete-*.zip` for local UAT).
3. **Wipe schema (optional):** `make dbempty` recreates the DB volume and applies `sql/*.sql` only.
4. **Import:** `tbload --mode erase-reload -i /tmp/tb-snap.zip` or `tbload --mode erase-reload -i /path/to/expanded-snapshot-dir` or `curl -fsS -X POST -F "snapshot=@/tmp/tb-snap.zip" -F "restore_mode=erase-reload" "http://127.0.0.1:8080/backup/import"`. Invalid modes such as `erase-spice-girls-music` are rejected. Mode prefixes (`a`, `o`, `e`, `erase-`) resolve to the single matching canonical value.
5. **Sanity check:** `curl -fsS http://127.0.0.1:8080/health` and confirm accounts / journals in the UI match expectations.

**Local UAT bootstrap:** place a complete snapshot at `examples/tallybadger-complete-*.zip` (gitignored), start the API, then run **`make dbclean`** (runs `tbload --mode erase-reload` on the newest match).

`make backup-restore-drill-help` prints a short pointer to this section.

---

## Kubernetes

Compose is the reference for a single host (e.g. a Celeron box with 16 GB RAM). For Kubernetes: run the same API image, managed Postgres (or a StatefulSet), inject `TALLYBADGER_DATABASE_URL` via secrets, and front with an Ingress. No K8s manifests ship in-repo yet.

---

## Working style

Stakeholder steers; implementation and dependencies are handled in-repo (`pyproject.toml`, `pip install -e ".[dev]"`). When something new is needed, it gets declared in `pyproject.toml` and installed like any other Python project—no hand-wavy “install this random CPAN module” detours.
