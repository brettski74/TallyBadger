-- Party subtype, regex match patterns, default GL accounts (#46).

ALTER TABLE parties
  ADD COLUMN IF NOT EXISTS subtype TEXT,
  ADD COLUMN IF NOT EXISTS default_revenue_account_id BIGINT REFERENCES accounts(id),
  ADD COLUMN IF NOT EXISTS default_expense_account_id BIGINT REFERENCES accounts(id);

ALTER TABLE parties DROP CONSTRAINT IF EXISTS chk_party_default_revenue_role;
ALTER TABLE parties ADD CONSTRAINT chk_party_default_revenue_role
  CHECK (default_revenue_account_id IS NULL OR role IN ('customer', 'both'));

ALTER TABLE parties DROP CONSTRAINT IF EXISTS chk_party_default_expense_role;
ALTER TABLE parties ADD CONSTRAINT chk_party_default_expense_role
  CHECK (default_expense_account_id IS NULL OR role IN ('vendor', 'both'));

CREATE TABLE IF NOT EXISTS party_match_patterns (
  id BIGSERIAL PRIMARY KEY,
  party_id BIGINT NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
  pattern TEXT NOT NULL,
  sort_order INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (party_id, sort_order)
);

CREATE INDEX IF NOT EXISTS idx_party_match_patterns_party_id ON party_match_patterns(party_id);

INSERT INTO schema_migrations (version) VALUES ('014_party_subtype_patterns_defaults')
  ON CONFLICT DO NOTHING;
