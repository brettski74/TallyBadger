-- Cheque register and journal linkage (#90).

CREATE TABLE IF NOT EXISTS cheques (
  id                  BIGSERIAL PRIMARY KEY,
  credit_account_id   BIGINT NOT NULL REFERENCES accounts(id),
  debit_account_id    BIGINT NOT NULL REFERENCES accounts(id),
  summary             TEXT NOT NULL,
  cheque_number       INTEGER NOT NULL CHECK (cheque_number > 0),
  issue_date          DATE NOT NULL,
  cleared_date        DATE,
  amount              NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
  party_id            BIGINT REFERENCES parties(id),
  status              TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'cleared', 'void')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_cheques_summary_non_blank CHECK (BTRIM(summary) <> ''),
  CONSTRAINT chk_cheques_cleared_consistency CHECK (
    (status = 'cleared' AND cleared_date IS NOT NULL)
    OR (status IN ('open', 'void') AND cleared_date IS NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cheques_open_number_per_credit_account
  ON cheques (credit_account_id, cheque_number)
  WHERE (status = 'open');

CREATE INDEX IF NOT EXISTS idx_cheques_credit_account_id ON cheques(credit_account_id);
CREATE INDEX IF NOT EXISTS idx_cheques_debit_account_id ON cheques(debit_account_id);
CREATE INDEX IF NOT EXISTS idx_cheques_party_id ON cheques(party_id);

ALTER TABLE journal_entries
  ADD COLUMN IF NOT EXISTS cheque_id BIGINT REFERENCES cheques(id);

CREATE INDEX IF NOT EXISTS idx_journal_entries_cheque_id ON journal_entries(cheque_id);

INSERT INTO schema_migrations (version) VALUES ('018_cheques')
  ON CONFLICT DO NOTHING;
