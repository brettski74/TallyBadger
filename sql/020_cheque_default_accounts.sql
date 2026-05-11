-- Last-used cheque credit/debit defaults on ledger_settings (#105).
--
-- Logical traceability: default_cheque_credit_account_id -> "default-cheque-cr-account",
-- default_cheque_debit_account_id -> "default-cheque-dr-account". Both nullable so they
-- behave the same way as the existing settlement/unallocated defaults on this table.
-- Picker / API semantics (active + correct account type) live in application code; the
-- DB only enforces existence via these foreign keys.

ALTER TABLE ledger_settings
  ADD COLUMN IF NOT EXISTS default_cheque_credit_account_id BIGINT REFERENCES accounts(id),
  ADD COLUMN IF NOT EXISTS default_cheque_debit_account_id  BIGINT REFERENCES accounts(id);

-- New FKs default to NOT DEFERRABLE; migration 015 already deferred existing ledger_settings
-- FKs for snapshot import. Mirror that behaviour for the two new ones so /backup/import keeps
-- working when SET CONSTRAINTS ALL DEFERRED is in effect.
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
      AND c.conname IN (
        'ledger_settings_default_cheque_credit_account_id_fkey',
        'ledger_settings_default_cheque_debit_account_id_fkey'
      )
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

INSERT INTO schema_migrations (version) VALUES ('020_cheque_default_accounts')
ON CONFLICT DO NOTHING;
