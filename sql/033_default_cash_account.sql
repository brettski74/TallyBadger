-- Default cash account for accrual settlement lines on ledger_settings (#276).

ALTER TABLE ledger_settings
  ADD COLUMN IF NOT EXISTS default_cash_account_id BIGINT REFERENCES accounts(id);

DO $$
DECLARE
  r RECORD;
  stmt TEXT;
BEGIN
  FOR r IN
    SELECT c.conname, n.nspname AS schem, rel.relname AS tbl
    FROM pg_constraint c
    JOIN pg_class rel ON rel.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = rel.relnamespace
    WHERE n.nspname = 'public'
      AND rel.relname = 'ledger_settings'
      AND c.contype = 'f'
      AND c.conname = 'ledger_settings_default_cash_account_id_fkey'
  LOOP
    stmt := format(
      'ALTER TABLE %I.%I ALTER CONSTRAINT %I DEFERRABLE INITIALLY IMMEDIATE',
      r.schem,
      r.tbl,
      r.conname
    );
    EXECUTE stmt;
  END LOOP;
END$$;

INSERT INTO schema_migrations (version) VALUES ('033_default_cash_account')
ON CONFLICT DO NOTHING;
