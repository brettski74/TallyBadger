-- Deferrable constraint triggers: balanced journal entries at commit (#244).

DROP TRIGGER IF EXISTS journal_lines_balance_after_delete ON journal_lines;
DROP TRIGGER IF EXISTS journal_lines_balance_after_update ON journal_lines;
DROP TRIGGER IF EXISTS journal_lines_balance_after_insert ON journal_lines;
DROP TRIGGER IF EXISTS journal_entries_balance_after_insert ON journal_entries;

CREATE OR REPLACE FUNCTION enforce_journal_entry_balance(p_entry_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
  v_line_count BIGINT;
  v_total NUMERIC;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM journal_entries WHERE id = p_entry_id) THEN
    RETURN;
  END IF;

  SELECT COUNT(*)::bigint, SUM(amount)
  INTO v_line_count, v_total
  FROM journal_lines
  WHERE entry_id = p_entry_id;

  IF v_line_count < 2 THEN
    RAISE EXCEPTION
      'journal entry requires at least two lines (entry_id=%, line_count=%)',
      p_entry_id, v_line_count;
  END IF;

  IF v_total IS NULL OR v_total IS DISTINCT FROM 0 THEN
    RAISE EXCEPTION
      'journal entry is not balanced (entry_id=%, sum=%)',
      p_entry_id, v_total;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION trg_journal_entries_balance_after_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM enforce_journal_entry_balance(NEW.id);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION trg_journal_lines_balance_after_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  v_entry_id BIGINT;
BEGIN
  v_entry_id := COALESCE(NEW.entry_id, OLD.entry_id);
  PERFORM enforce_journal_entry_balance(v_entry_id);
  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE CONSTRAINT TRIGGER journal_entries_balance_after_insert
  AFTER INSERT ON journal_entries
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION trg_journal_entries_balance_after_insert();

CREATE CONSTRAINT TRIGGER journal_lines_balance_after_insert
  AFTER INSERT ON journal_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION trg_journal_lines_balance_after_change();

CREATE CONSTRAINT TRIGGER journal_lines_balance_after_update
  AFTER UPDATE ON journal_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION trg_journal_lines_balance_after_change();

CREATE CONSTRAINT TRIGGER journal_lines_balance_after_delete
  AFTER DELETE ON journal_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION trg_journal_lines_balance_after_change();

INSERT INTO schema_migrations (version) VALUES ('027_journal_entry_balance_deferrable')
  ON CONFLICT DO NOTHING;
