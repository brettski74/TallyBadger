-- Seed default suspense / unallocated accounts for CSV import (#48).

INSERT INTO accounts (name, type, is_active)
SELECT seeded.name, seeded.type, TRUE
FROM (
  VALUES
    ('Unallocated Debits', 'suspense'),
    ('Unallocated Credits', 'suspense')
) AS seeded(name, type)
WHERE NOT EXISTS (
  SELECT 1
  FROM accounts a
  WHERE LOWER(a.name) = LOWER(seeded.name)
);

UPDATE ledger_settings
SET
  unallocated_debits_account_id = COALESCE(
    unallocated_debits_account_id,
    (SELECT id FROM accounts WHERE LOWER(name) = 'unallocated debits' LIMIT 1)
  ),
  unallocated_credits_account_id = COALESCE(
    unallocated_credits_account_id,
    (SELECT id FROM accounts WHERE LOWER(name) = 'unallocated credits' LIMIT 1)
  ),
  updated_at = NOW()
WHERE id = 1;

INSERT INTO schema_migrations (version) VALUES ('012_seed_unallocated_suspense_accounts')
ON CONFLICT DO NOTHING;
