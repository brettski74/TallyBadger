# Database migrations

Apply in order with `psql` or your migration runner of choice. Example:

```bash
psql "$DATABASE_URL" -f sql/001_placeholder.sql
psql "$DATABASE_URL" -f sql/002_ledger_mvp.sql
```

Or use the built-in runner (applies all `NNN_*.sql` files in order):

```bash
tallybadger-migrate
```

When the schema stabilizes, consider `sqitch`, `yoyo-migrations`, or Alembic.

## Dev seed (`dev_seed.sql`) — not a migration

Numbered `NNN_*.sql` files are **schema migrations** and run in all environments via `tallybadger-migrate`.

**`sql/dev_seed.sql`** is **dev-only**: idempotent `INSERT`s for accounts, parties, `cel_rule_sets`, and `import_templates`. It is **not** part of the migration glob and is **not** applied in production unless someone runs it manually.

Workflow:

1. After `make dbclean`, migrations run, then **`make dev-seed`** loads `dev_seed.sql` (dbclean does both).
2. **`make test`** / **`make db-migrate-local`** apply **only** numbered migrations — tests do not load `dev_seed.sql`.
3. To snapshot your manual-testing DB into the repo: set `TALLYBADGER_DATABASE_URL`, then **`make export-dev-seed`** (alias: `make export-bootstrap`). Commit `sql/dev_seed.sql` if you want to share that fixture.
