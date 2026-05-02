-- Suspense account type, unallocated import defaults on ledger_settings, journal review flag (#48).

ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_type_check;
ALTER TABLE accounts ADD CONSTRAINT accounts_type_check
  CHECK (type IN ('asset', 'liability', 'equity', 'revenue', 'expense', 'suspense'));

ALTER TABLE ledger_settings
  ADD COLUMN IF NOT EXISTS unallocated_debits_account_id BIGINT REFERENCES accounts(id),
  ADD COLUMN IF NOT EXISTS unallocated_credits_account_id BIGINT REFERENCES accounts(id);

ALTER TABLE journal_entries
  ADD COLUMN IF NOT EXISTS requires_review BOOLEAN NOT NULL DEFAULT FALSE;

INSERT INTO schema_migrations (version) VALUES ('011_suspense_unallocated_and_review')
ON CONFLICT DO NOTHING;
