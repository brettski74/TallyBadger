-- Seed default settlement accounts for fresh databases.

INSERT INTO accounts (name, type, is_active)
SELECT seeded.name, seeded.type, TRUE
FROM (
  VALUES
    ('Accounts Receivable', 'asset'),
    ('Accounts Payable', 'liability'),
    ('Unearned Revenue', 'liability')
) AS seeded(name, type)
WHERE NOT EXISTS (
  SELECT 1
  FROM accounts a
  WHERE LOWER(a.name) = LOWER(seeded.name)
);

UPDATE ledger_settings
SET
  accounts_receivable_account_id = COALESCE(
    accounts_receivable_account_id,
    (SELECT id FROM accounts WHERE LOWER(name) = 'accounts receivable' LIMIT 1)
  ),
  accounts_payable_account_id = COALESCE(
    accounts_payable_account_id,
    (SELECT id FROM accounts WHERE LOWER(name) = 'accounts payable' LIMIT 1)
  ),
  unearned_revenue_account_id = COALESCE(
    unearned_revenue_account_id,
    (SELECT id FROM accounts WHERE LOWER(name) = 'unearned revenue' LIMIT 1)
  ),
  updated_at = NOW()
WHERE id = 1;

INSERT INTO schema_migrations (version) VALUES ('008_seed_default_settlement_accounts')
ON CONFLICT DO NOTHING;
