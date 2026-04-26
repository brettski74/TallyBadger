-- Add weekend business-day adjustment flag for monthly/yearly accruals.

ALTER TABLE accrual_plans
  ADD COLUMN IF NOT EXISTS business_day_adjust BOOLEAN NOT NULL DEFAULT FALSE;

INSERT INTO schema_migrations (version) VALUES ('005_accrual_business_day_adjust')
  ON CONFLICT DO NOTHING;
