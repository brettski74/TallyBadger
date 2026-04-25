# Database migrations

Apply in order with `psql` or your migration runner of choice. Example:

```bash
psql "$DATABASE_URL" -f sql/001_placeholder.sql
psql "$DATABASE_URL" -f sql/002_ledger_mvp.sql
```

When the schema stabilizes, consider `sqitch`, `yoyo-migrations`, or Alembic.
