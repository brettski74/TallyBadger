-- Deferrable FKs on cheques and journal_entries.cheque_id for snapshot import (#90).

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
      AND c.contype = 'f'
      AND (
        rel.relname = 'cheques'
        OR (rel.relname = 'journal_entries' AND c.conname = 'journal_entries_cheque_id_fkey')
      )
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

INSERT INTO schema_migrations (version) VALUES ('019_cheques_snapshot_fks_deferrable')
ON CONFLICT DO NOTHING;
