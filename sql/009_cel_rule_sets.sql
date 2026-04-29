-- Persisted CEL import rule sets (#37): JSON matches CelRuleSet (Pydantic).

CREATE TABLE IF NOT EXISTS cel_rule_sets (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  definition   JSONB NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT cel_rule_sets_name_unique UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_cel_rule_sets_name ON cel_rule_sets (name);

INSERT INTO schema_migrations (version) VALUES ('009_cel_rule_sets')
  ON CONFLICT DO NOTHING;
