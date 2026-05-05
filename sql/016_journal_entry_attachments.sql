-- Journal entry attachments: blobs, many-to-many links, max upload size on ledger_settings (#78).

ALTER TABLE ledger_settings
  ADD COLUMN IF NOT EXISTS max_attachment_upload_bytes BIGINT NOT NULL DEFAULT 5242880
  CHECK (max_attachment_upload_bytes > 0);

CREATE TABLE IF NOT EXISTS attachments (
  id BIGSERIAL PRIMARY KEY,
  blob BYTEA NOT NULL,
  summary TEXT NOT NULL,
  external_reference TEXT,
  mime_type TEXT NOT NULL,
  original_filename TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_attachments_summary_non_blank CHECK (BTRIM(summary) <> '')
);

CREATE TABLE IF NOT EXISTS journal_entry_attachments (
  id BIGSERIAL PRIMARY KEY,
  journal_entry_id BIGINT NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
  attachment_id BIGINT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (journal_entry_id, attachment_id)
);

CREATE INDEX IF NOT EXISTS idx_journal_entry_attachments_entry_id
  ON journal_entry_attachments(journal_entry_id);

CREATE INDEX IF NOT EXISTS idx_journal_entry_attachments_attachment_id
  ON journal_entry_attachments(attachment_id);

CREATE OR REPLACE FUNCTION purge_orphan_attachments()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  DELETE FROM attachments a
  WHERE a.id = OLD.attachment_id
    AND NOT EXISTS (
      SELECT 1 FROM journal_entry_attachments j WHERE j.attachment_id = a.id
    );
  RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_journal_entry_attachments_purge_orphan ON journal_entry_attachments;
CREATE TRIGGER trg_journal_entry_attachments_purge_orphan
AFTER DELETE ON journal_entry_attachments
FOR EACH ROW EXECUTE FUNCTION purge_orphan_attachments();

INSERT INTO schema_migrations (version) VALUES ('016_journal_entry_attachments')
ON CONFLICT DO NOTHING;
