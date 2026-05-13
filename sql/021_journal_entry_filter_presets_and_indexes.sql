-- Named journal-entry list filter presets and supporting indexes (#107).

CREATE TABLE IF NOT EXISTS journal_entry_filter_presets (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  definition  JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT journal_entry_filter_presets_name_unique UNIQUE (name),
  CONSTRAINT chk_journal_entry_filter_presets_name_non_blank
    CHECK (BTRIM(name) <> '')
);

CREATE INDEX IF NOT EXISTS idx_journal_entry_filter_presets_name
  ON journal_entry_filter_presets (name);

-- Composite indexes so the journal-entries list can answer
-- "entries touching any of these account ids / party ids" via an index-only
-- EXISTS lookup keyed on (filter column, entry_id).
CREATE INDEX IF NOT EXISTS idx_journal_lines_account_id_entry_id
  ON journal_lines (account_id, entry_id);

CREATE INDEX IF NOT EXISTS idx_journal_lines_party_id_entry_id
  ON journal_lines (party_id, entry_id)
  WHERE party_id IS NOT NULL;

INSERT INTO schema_migrations (version) VALUES ('021_journal_entry_filter_presets_and_indexes')
  ON CONFLICT DO NOTHING;
