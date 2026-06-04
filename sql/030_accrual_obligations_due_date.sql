-- Nullable due date on accrual obligations (scanner US-2, #259).

ALTER TABLE accrual_obligations
  ADD COLUMN IF NOT EXISTS due_date DATE;

INSERT INTO schema_migrations (version) VALUES ('030_accrual_obligations_due_date')
  ON CONFLICT DO NOTHING;
