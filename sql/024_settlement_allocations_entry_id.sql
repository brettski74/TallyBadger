-- Collapse settlement_events into settlement_allocations (#153).
-- Settlements group by shared entry_id (FK → journal_entries); drop event header table.

ALTER TABLE settlement_allocations
  ADD COLUMN IF NOT EXISTS entry_id BIGINT REFERENCES journal_entries(id);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'settlement_allocations'
      AND column_name = 'settlement_event_id'
  ) THEN
    UPDATE settlement_allocations sa
    SET entry_id = se.entry_id
    FROM settlement_events se
    WHERE sa.settlement_event_id = se.id
      AND sa.entry_id IS NULL;

    ALTER TABLE settlement_allocations
      ALTER COLUMN entry_id SET NOT NULL;

    ALTER TABLE settlement_allocations
      DROP COLUMN settlement_event_id;
  END IF;
END$$;

DROP TABLE IF EXISTS settlement_events;

CREATE INDEX IF NOT EXISTS idx_settlement_allocations_entry_id
  ON settlement_allocations(entry_id);

-- Deferrable FK for snapshot import (same pattern as migration 015).
DO $$
DECLARE
  r RECORD;
  stmt TEXT;
BEGIN
  FOR r IN
    SELECT c.conname, n.nspname AS schem, rel.relname AS tbl
    FROM pg_constraint c
    JOIN pg_class rel ON rel.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = rel.relnamespace
    WHERE n.nspname = 'public'
      AND rel.relname = 'settlement_allocations'
      AND c.contype = 'f'
      AND c.conname LIKE '%entry_id%'
  LOOP
    stmt := format(
      'ALTER TABLE %I.%I ALTER CONSTRAINT %I DEFERRABLE INITIALLY IMMEDIATE',
      r.schem,
      r.tbl,
      r.conname
    );
    EXECUTE stmt;
  END LOOP;
END$$;

INSERT INTO schema_migrations (version) VALUES ('024_settlement_allocations_entry_id')
ON CONFLICT DO NOTHING;
