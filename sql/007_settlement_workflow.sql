-- Settlement workflow: configurable role accounts + obligations subledger.

CREATE TABLE IF NOT EXISTS ledger_settings (
  id                              SMALLINT PRIMARY KEY CHECK (id = 1),
  accounts_receivable_account_id  BIGINT REFERENCES accounts(id),
  accounts_payable_account_id     BIGINT REFERENCES accounts(id),
  unearned_revenue_account_id     BIGINT REFERENCES accounts(id),
  updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ledger_settings (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS accrual_obligations (
  id              BIGSERIAL PRIMARY KEY,
  party_id        BIGINT NOT NULL REFERENCES parties(id),
  accrual_plan_id BIGINT REFERENCES accrual_plans(id),
  source_entry_id BIGINT REFERENCES journal_entries(id),
  source_line_id  BIGINT REFERENCES journal_lines(id),
  obligation_type TEXT NOT NULL CHECK (obligation_type IN ('receivable', 'payable', 'unearned')),
  status          TEXT NOT NULL CHECK (status IN ('open', 'partially_settled', 'settled', 'reconciled')),
  original_amount NUMERIC(18,2) NOT NULL CHECK (original_amount > 0),
  open_amount     NUMERIC(18,2) NOT NULL CHECK (open_amount >= 0 AND open_amount <= original_amount),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_accrual_obligations_party_status
  ON accrual_obligations(party_id, status);

CREATE TABLE IF NOT EXISTS settlement_events (
  id              BIGSERIAL PRIMARY KEY,
  party_id        BIGINT NOT NULL REFERENCES parties(id),
  settlement_type TEXT NOT NULL CHECK (settlement_type IN ('receipt', 'payment')),
  event_date      DATE NOT NULL,
  amount          NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  cash_account_id BIGINT NOT NULL REFERENCES accounts(id),
  entry_id        BIGINT NOT NULL REFERENCES journal_entries(id),
  note            TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settlement_allocations (
  id                  BIGSERIAL PRIMARY KEY,
  settlement_event_id BIGINT NOT NULL REFERENCES settlement_events(id) ON DELETE CASCADE,
  obligation_id       BIGINT NOT NULL REFERENCES accrual_obligations(id),
  amount              NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version) VALUES ('007_settlement_workflow')
ON CONFLICT DO NOTHING;
