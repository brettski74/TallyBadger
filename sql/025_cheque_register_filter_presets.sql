-- Named cheque-register list filter presets (#196).

CREATE TABLE IF NOT EXISTS cheque_register_filter_presets (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  definition  JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT cheque_register_filter_presets_name_unique UNIQUE (name),
  CONSTRAINT chk_cheque_register_filter_presets_name_non_blank
    CHECK (BTRIM(name) <> '')
);

CREATE INDEX IF NOT EXISTS idx_cheque_register_filter_presets_name
  ON cheque_register_filter_presets (name);

INSERT INTO schema_migrations (version) VALUES ('025_cheque_register_filter_presets')
  ON CONFLICT DO NOTHING;
