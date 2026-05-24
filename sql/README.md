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

## Local development workflow

Numbered `NNN_*.sql` files are **schema migrations** and run in all environments via `tallybadger-migrate`.

1. **`make dbempty`** recreates the Compose DB volume and applies numbered migrations only.
2. **`make test`** / **`make db-migrate-local`** apply **only** numbered migrations — tests do not load snapshot fixtures automatically.
3. **`make dbclean`** restores the newest **`examples/tallybadger-complete-*.zip`** via **`tbload`** (API must be running). Export a complete snapshot into `examples/` when you need fresh UAT data (ZIPs are gitignored).
