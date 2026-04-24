-- Placeholder: chart of accounts, journals, and property dimensions will live here.
-- See README.md “Data model (direction)” for the intended shape.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version     TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version) VALUES ('001_placeholder')
  ON CONFLICT DO NOTHING;
