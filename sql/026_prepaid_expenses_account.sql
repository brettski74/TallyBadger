-- Prepaid expenses role account on ledger_settings (#229).

ALTER TABLE ledger_settings
  ADD COLUMN IF NOT EXISTS prepaid_expenses_account_id BIGINT REFERENCES accounts(id);

INSERT INTO accounts (name, type, is_active)
SELECT seeded.name, seeded.type, TRUE
FROM (
  VALUES
    ('Prepaid Expenses', 'asset')
) AS seeded(name, type)
WHERE NOT EXISTS (
  SELECT 1
  FROM accounts a
  WHERE LOWER(a.name) = LOWER(seeded.name)
);

UPDATE ledger_settings
SET
  prepaid_expenses_account_id = COALESCE(
    prepaid_expenses_account_id,
    (SELECT id FROM accounts WHERE LOWER(name) = 'prepaid expenses' LIMIT 1)
  ),
  updated_at = NOW()
WHERE id = 1;

INSERT INTO schema_migrations (version) VALUES ('026_prepaid_expenses_account')
ON CONFLICT DO NOTHING;
