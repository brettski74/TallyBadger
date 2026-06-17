-- Multi-line journal_lines.settlement_allocation_id linkage (#277).

DROP INDEX IF EXISTS idx_journal_lines_settlement_allocation_id_unique;

CREATE INDEX IF NOT EXISTS idx_journal_lines_settlement_allocation_id
  ON journal_lines(settlement_allocation_id)
  WHERE settlement_allocation_id IS NOT NULL;

CREATE OR REPLACE FUNCTION enforce_settlement_allocation_line_sum(p_allocation_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
  v_alloc_amount NUMERIC;
  v_line_sum NUMERIC;
  v_line_count BIGINT;
BEGIN
  IF p_allocation_id IS NULL THEN
    RETURN;
  END IF;

  SELECT amount INTO v_alloc_amount
  FROM settlement_allocations
  WHERE id = p_allocation_id;

  IF NOT FOUND THEN
    RETURN;
  END IF;

  SELECT COUNT(*)::bigint, COALESCE(SUM(ABS(amount)), 0)
  INTO v_line_count, v_line_sum
  FROM journal_lines
  WHERE settlement_allocation_id = p_allocation_id;

  IF v_line_count = 0 THEN
    RETURN;
  END IF;

  IF v_line_sum IS DISTINCT FROM v_alloc_amount THEN
    RAISE EXCEPTION
      'settlement allocation line amounts do not sum to allocation amount (allocation_id=%, sum_abs=%, allocation_amount=%)',
      p_allocation_id, v_line_sum, v_alloc_amount;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION trg_journal_lines_settlement_allocation_after_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  v_allocation_id BIGINT;
BEGIN
  v_allocation_id := COALESCE(NEW.settlement_allocation_id, OLD.settlement_allocation_id);
  IF v_allocation_id IS NOT NULL THEN
    PERFORM enforce_settlement_allocation_line_sum(v_allocation_id);
  END IF;
  IF TG_OP = 'UPDATE'
     AND OLD.settlement_allocation_id IS DISTINCT FROM NEW.settlement_allocation_id
     AND OLD.settlement_allocation_id IS NOT NULL THEN
    PERFORM enforce_settlement_allocation_line_sum(OLD.settlement_allocation_id);
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION trg_settlement_allocations_amount_after_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.amount IS DISTINCT FROM OLD.amount THEN
    PERFORM enforce_settlement_allocation_line_sum(NEW.id);
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS journal_lines_settlement_allocation_after_insert ON journal_lines;
DROP TRIGGER IF EXISTS journal_lines_settlement_allocation_after_update ON journal_lines;
DROP TRIGGER IF EXISTS journal_lines_settlement_allocation_after_delete ON journal_lines;
DROP TRIGGER IF EXISTS settlement_allocations_amount_after_update ON settlement_allocations;

CREATE CONSTRAINT TRIGGER journal_lines_settlement_allocation_after_insert
  AFTER INSERT ON journal_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION trg_journal_lines_settlement_allocation_after_change();

CREATE CONSTRAINT TRIGGER journal_lines_settlement_allocation_after_update
  AFTER UPDATE ON journal_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION trg_journal_lines_settlement_allocation_after_change();

CREATE CONSTRAINT TRIGGER journal_lines_settlement_allocation_after_delete
  AFTER DELETE ON journal_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION trg_journal_lines_settlement_allocation_after_change();

CREATE CONSTRAINT TRIGGER settlement_allocations_amount_after_update
  AFTER UPDATE OF amount ON settlement_allocations
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION trg_settlement_allocations_amount_after_update();

INSERT INTO schema_migrations (version) VALUES ('034_journal_lines_settlement_allocation_multi_line')
  ON CONFLICT DO NOTHING;
