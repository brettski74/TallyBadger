-- CSV import batches: persistence and journal linkage (#134; parent #49).

CREATE TABLE IF NOT EXISTS import_batches (
  id               BIGSERIAL PRIMARY KEY,
  basename         TEXT NOT NULL,
  content_sha256   BYTEA NOT NULL CHECK (octet_length(content_sha256) = 32),
  loaded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_import_batches_basename_non_blank CHECK (BTRIM(basename) <> '')
);

-- Active batches: basename uniqueness is case-insensitive for UX (#49).
CREATE UNIQUE INDEX IF NOT EXISTS uq_import_batches_active_basename_ci
  ON import_batches (LOWER(basename))
  WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_import_batches_loaded_at ON import_batches (loaded_at);

ALTER TABLE journal_entries
  ADD COLUMN IF NOT EXISTS import_batch_id BIGINT REFERENCES import_batches(id);

CREATE INDEX IF NOT EXISTS idx_journal_entries_import_batch_id
  ON journal_entries (import_batch_id);

INSERT INTO schema_migrations (version) VALUES ('022_import_batches_and_journal_fk')
  ON CONFLICT DO NOTHING;
