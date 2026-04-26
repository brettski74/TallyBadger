-- Party model and mandatory journal summaries for issue #30.

CREATE TABLE IF NOT EXISTS parties (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  role        TEXT NOT NULL DEFAULT 'both'
              CHECK (role IN ('customer', 'vendor', 'both', 'other')),
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE journal_entries
  ADD COLUMN IF NOT EXISTS summary TEXT;

UPDATE journal_entries
SET summary = COALESCE(NULLIF(BTRIM(description), ''), 'Legacy entry')
WHERE summary IS NULL OR BTRIM(summary) = '';

ALTER TABLE journal_entries
  ALTER COLUMN summary SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_journal_entries_summary_non_blank'
  ) THEN
    ALTER TABLE journal_entries
      ADD CONSTRAINT chk_journal_entries_summary_non_blank
      CHECK (BTRIM(summary) <> '');
  END IF;
END $$;

ALTER TABLE journal_lines
  ADD COLUMN IF NOT EXISTS party_id BIGINT REFERENCES parties(id);

CREATE INDEX IF NOT EXISTS idx_journal_lines_party_id ON journal_lines(party_id);

INSERT INTO schema_migrations (version) VALUES ('003_parties_and_journal_summary')
  ON CONFLICT DO NOTHING;
