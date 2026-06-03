-- Scanner settings on ledger_settings, attachment link_count (#258).

ALTER TABLE ledger_settings
  ADD COLUMN IF NOT EXISTS scanner_device_uri TEXT,
  ADD COLUMN IF NOT EXISTS max_scanned_pages INTEGER NOT NULL DEFAULT 50
    CHECK (max_scanned_pages > 0),
  ADD COLUMN IF NOT EXISTS scan_dpi INTEGER NOT NULL DEFAULT 300
    CHECK (scan_dpi > 0),
  ADD COLUMN IF NOT EXISTS scan_color_mode TEXT NOT NULL DEFAULT 'greyscale'
    CHECK (scan_color_mode IN ('greyscale'));

ALTER TABLE attachments
  ADD COLUMN IF NOT EXISTS link_count INTEGER NOT NULL DEFAULT 0
    CHECK (link_count >= 0);

UPDATE attachments a
SET link_count = (
  SELECT COUNT(*)::INTEGER
  FROM journal_entry_attachments j
  WHERE j.attachment_id = a.id
);

CREATE OR REPLACE FUNCTION maintain_attachment_link_count()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE attachments
    SET link_count = link_count + 1
    WHERE id = NEW.attachment_id;
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    UPDATE attachments
    SET link_count = link_count - 1
    WHERE id = OLD.attachment_id;
    RETURN OLD;
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_journal_entry_attachments_link_count ON journal_entry_attachments;
CREATE TRIGGER trg_journal_entry_attachments_link_count
AFTER INSERT OR DELETE ON journal_entry_attachments
FOR EACH ROW EXECUTE FUNCTION maintain_attachment_link_count();

INSERT INTO schema_migrations (version) VALUES ('028_scanner_link_count')
ON CONFLICT DO NOTHING;
