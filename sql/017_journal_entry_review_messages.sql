-- Journal entry review messages (#89): discrete reasons; requires_review stays synced via trigger.

CREATE TABLE IF NOT EXISTS journal_entry_review_messages (
  id              BIGSERIAL PRIMARY KEY,
  journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
  message         TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT journal_entry_review_messages_message_nonempty
    CHECK (length(trim(message)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_journal_entry_review_messages_entry
  ON journal_entry_review_messages(journal_entry_id);

CREATE OR REPLACE FUNCTION tallybadger_sync_journal_entry_requires_review()
RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    UPDATE journal_entries
    SET
      requires_review = EXISTS(
        SELECT 1
        FROM journal_entry_review_messages m
        WHERE m.journal_entry_id = OLD.journal_entry_id
      ),
      updated_at = NOW()
    WHERE id = OLD.journal_entry_id;
    RETURN OLD;
  ELSIF TG_OP = 'INSERT' THEN
    UPDATE journal_entries
    SET requires_review = TRUE, updated_at = NOW()
    WHERE id = NEW.journal_entry_id;
    RETURN NEW;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_journal_entry_review_messages_sync ON journal_entry_review_messages;
CREATE TRIGGER trg_journal_entry_review_messages_sync
  AFTER INSERT OR DELETE ON journal_entry_review_messages
  FOR EACH ROW
  EXECUTE FUNCTION tallybadger_sync_journal_entry_requires_review();

INSERT INTO journal_entry_review_messages (journal_entry_id, message)
SELECT je.id,
  'This entry was flagged for review before per-message review reasons existed.'
FROM journal_entries je
WHERE je.requires_review IS TRUE
  AND NOT EXISTS (
    SELECT 1 FROM journal_entry_review_messages m WHERE m.journal_entry_id = je.id
  );

INSERT INTO schema_migrations (version) VALUES ('017_journal_entry_review_messages')
ON CONFLICT DO NOTHING;
