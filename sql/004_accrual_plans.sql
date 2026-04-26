-- Accrual plans and generated-entry linkage for issue #17.

CREATE TABLE IF NOT EXISTS accrual_plans (
  id                    BIGSERIAL PRIMARY KEY,
  name                  TEXT NOT NULL UNIQUE,
  direction             TEXT NOT NULL CHECK (direction IN ('revenue', 'expense')),
  party_id              BIGINT NOT NULL REFERENCES parties(id),
  target_account_id     BIGINT NOT NULL REFERENCES accounts(id),
  bridge_account_id     BIGINT NOT NULL REFERENCES accounts(id),
  frequency             TEXT NOT NULL CHECK (frequency IN ('weekly', 'monthly_day', 'monthly_relative', 'yearly')),
  start_date            DATE NOT NULL,
  end_date              DATE NOT NULL,
  amount                NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  summary_template      TEXT NOT NULL CHECK (BTRIM(summary_template) <> ''),
  description_template  TEXT,
  day_of_week           INT,
  day_of_month          INT,
  month_of_year         INT,
  relative_direction    TEXT CHECK (relative_direction IN ('before', 'after')),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_accrual_plans_date_range CHECK (end_date >= start_date)
);

ALTER TABLE journal_entries
  ADD COLUMN IF NOT EXISTS accrual_plan_id BIGINT REFERENCES accrual_plans(id);

CREATE INDEX IF NOT EXISTS idx_journal_entries_accrual_plan_id
  ON journal_entries(accrual_plan_id);

INSERT INTO schema_migrations (version) VALUES ('004_accrual_plans')
  ON CONFLICT DO NOTHING;
