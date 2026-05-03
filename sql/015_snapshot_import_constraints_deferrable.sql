-- Deferrable snapshot-table foreign keys for ZIP import (#68 follow-up).
-- PostgreSQL only supports ALTER CONSTRAINT ... DEFERRABLE on FOREIGN KEY constraints
-- (not CHECK / PRIMARY KEY / UNIQUE without dropping and recreating the constraint).
-- Normal sessions: INITIALLY IMMEDIATE (checked each statement, same as before).
-- Import transaction runs SET CONSTRAINTS ALL DEFERRED so FKs are validated at COMMIT.

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
      AND rel.relname IN (
        'accounts',
        'parties',
        'party_match_patterns',
        'accrual_plans',
        'ledger_settings',
        'cel_rule_sets',
        'journal_entries',
        'journal_lines',
        'accrual_obligations',
        'settlement_events',
        'settlement_allocations',
        'import_templates'
      )
      AND c.contype = 'f'
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

INSERT INTO schema_migrations (version) VALUES ('015_snapshot_import_constraints_deferrable')
  ON CONFLICT DO NOTHING;
