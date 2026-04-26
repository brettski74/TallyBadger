-- Remove unsupported monthly_relative recurrence shape.

ALTER TABLE accrual_plans
  DROP CONSTRAINT IF EXISTS accrual_plans_frequency_check;

ALTER TABLE accrual_plans
  ADD CONSTRAINT accrual_plans_frequency_check
  CHECK (frequency IN ('weekly', 'monthly_day', 'yearly'));

ALTER TABLE accrual_plans
  DROP COLUMN IF EXISTS relative_direction;

INSERT INTO schema_migrations (version) VALUES ('006_remove_monthly_relative_accrual_plan_frequency')
  ON CONFLICT DO NOTHING;
