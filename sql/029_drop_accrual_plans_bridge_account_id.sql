-- Accrual plan bridge is inferred from direction + ledger settings at post time (#235).

ALTER TABLE accrual_plans DROP COLUMN IF EXISTS bridge_account_id;

INSERT INTO schema_migrations (version) VALUES ('029_drop_accrual_plans_bridge_account_id')
  ON CONFLICT DO NOTHING;
