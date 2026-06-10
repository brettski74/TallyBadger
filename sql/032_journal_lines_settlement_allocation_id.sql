-- Durable line ↔ allocation linkage (#270).

ALTER TABLE journal_lines
  ADD COLUMN IF NOT EXISTS settlement_allocation_id BIGINT
  REFERENCES settlement_allocations(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_lines_settlement_allocation_id_unique
  ON journal_lines(settlement_allocation_id)
  WHERE settlement_allocation_id IS NOT NULL;

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
      AND rel.relname = 'journal_lines'
      AND c.contype = 'f'
      AND c.conname LIKE '%settlement_allocation_id%'
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

-- Collapsed same-day accruals: source bridge line when amount still matches allocation.
UPDATE journal_lines jl
SET settlement_allocation_id = sa.id
FROM settlement_allocations sa
INNER JOIN accrual_obligations ao ON ao.id = sa.obligation_id
INNER JOIN journal_entries je ON je.id = sa.entry_id
WHERE jl.id = ao.source_line_id
  AND sa.entry_id = je.id
  AND je.accrual_plan_id IS NOT NULL
  AND ABS(jl.amount) = sa.amount
  AND jl.settlement_allocation_id IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM journal_lines jl_linked
    WHERE jl_linked.settlement_allocation_id = sa.id
  );

-- Collapsed partial same-day: cash line on accrual entry (not the source bridge line).
UPDATE journal_lines jl
SET settlement_allocation_id = matched.allocation_id
FROM (
  SELECT sa.id AS allocation_id,
         (
           SELECT jl2.id
           FROM journal_lines jl2
           INNER JOIN journal_entries je2 ON je2.id = jl2.entry_id
           INNER JOIN accrual_obligations ao2 ON ao2.id = sa.obligation_id
           WHERE jl2.entry_id = sa.entry_id
             AND je2.accrual_plan_id IS NOT NULL
             AND jl2.id <> ao2.source_line_id
             AND jl2.party_id = ao2.party_id
             AND ABS(jl2.amount) = sa.amount
             AND jl2.settlement_allocation_id IS NULL
           ORDER BY jl2.id DESC
           LIMIT 1
         ) AS line_id
  FROM settlement_allocations sa
  WHERE NOT EXISTS (
    SELECT 1
    FROM journal_lines jl_linked
    WHERE jl_linked.settlement_allocation_id = sa.id
  )
) matched
WHERE jl.id = matched.line_id
  AND matched.line_id IS NOT NULL
  AND jl.settlement_allocation_id IS NULL;

-- Per-obligation bridge lines on non-collapsed settlement entries (unambiguous match only).
UPDATE journal_lines jl
SET settlement_allocation_id = pick.allocation_id
FROM (
  SELECT sa.id AS allocation_id,
         MIN(jl2.id) AS line_id
  FROM settlement_allocations sa
  INNER JOIN accrual_obligations ao ON ao.id = sa.obligation_id
  INNER JOIN journal_entries je ON je.id = sa.entry_id
  INNER JOIN journal_lines jl2 ON jl2.entry_id = sa.entry_id
  INNER JOIN ledger_settings ls ON ls.id = 1
  WHERE je.accrual_plan_id IS NULL
    AND jl2.party_id = ao.party_id
    AND ABS(jl2.amount) = sa.amount
    AND jl2.settlement_allocation_id IS NULL
    AND NOT EXISTS (
      SELECT 1
      FROM journal_lines jl_linked
      WHERE jl_linked.settlement_allocation_id = sa.id
    )
    AND (
      (
        ao.obligation_type = 'receivable'
        AND jl2.account_id IN (
          ls.accounts_receivable_account_id,
          ls.unearned_revenue_account_id
        )
      )
      OR (
        ao.obligation_type = 'payable'
        AND jl2.account_id IN (
          ls.accounts_payable_account_id,
          ls.prepaid_expenses_account_id
        )
      )
    )
  GROUP BY sa.id
  HAVING COUNT(jl2.id) = 1
) pick
WHERE jl.id = pick.line_id
  AND jl.settlement_allocation_id IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM journal_lines jl_other
    WHERE jl_other.settlement_allocation_id = pick.allocation_id
  );

INSERT INTO schema_migrations (version) VALUES ('032_journal_lines_settlement_allocation_id')
ON CONFLICT DO NOTHING;
