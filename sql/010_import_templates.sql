-- Saved CSV import templates (#38): column mapping + optional CEL rule set.

CREATE TABLE IF NOT EXISTS import_templates (
  id                  BIGSERIAL PRIMARY KEY,
  name                TEXT NOT NULL,
  has_header_row      BOOLEAN NOT NULL DEFAULT FALSE,
  columns_definition  JSONB NOT NULL,
  cel_rule_set_id     BIGINT REFERENCES cel_rule_sets(id) ON DELETE SET NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT import_templates_name_unique UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_import_templates_name ON import_templates (name);
CREATE INDEX IF NOT EXISTS idx_import_templates_cel_rule_set_id ON import_templates (cel_rule_set_id);

INSERT INTO schema_migrations (version) VALUES ('010_import_templates')
  ON CONFLICT DO NOTHING;
