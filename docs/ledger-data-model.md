# Ledger data model — journals, obligations, settlements, import batches

This document is the **relationship map** for core ledger tables: how journal entries, accrual obligations, settlement allocations, and CSV import batches connect, and what **unload import batch** can and cannot roll back. It complements **[ARCH.md](../ARCH.md)** (subsystem boundaries) and **[docs/import-rules-engine.md](import-rules-engine.md)** (CSV attribute bags).

Parent workstream: [GitHub #45](https://github.com/brettski74/TallyBadger/issues/45). Settlement model collapsed in [#153](https://github.com/brettski74/TallyBadger/issues/153); CSV `line[]` settlement lands in [#151](https://github.com/brettski74/TallyBadger/issues/151).

---

## Entity-relationship diagram

```mermaid
erDiagram
    import_batches ||--o{ journal_entries : "tags (import_batch_id)"
    accrual_plans ||--o{ journal_entries : "tags (accrual_plan_id)"
    journal_entries ||--|{ journal_lines : "contains"
    journal_entries ||--o| cheques : "optional cheque_id"
    accrual_plans ||--o{ accrual_obligations : "schedules"
    journal_entries ||--o{ accrual_obligations : "source_entry_id"
    journal_lines ||--o{ accrual_obligations : "source_line_id (bridge)"
    parties ||--o{ accrual_obligations : "party_id"
    journal_entries ||--o{ settlement_allocations : "entry_id (settlement GL)"
    accrual_obligations ||--o{ settlement_allocations : "obligation_id"
    parties ||--o{ journal_lines : "optional party_id"
    accounts ||--o{ journal_lines : "account_id"

    import_batches {
        bigint id PK
        text basename
        bytea content_sha256
        timestamptz loaded_at
    }

    journal_entries {
        bigint id PK
        date entry_date
        text summary
        bigint import_batch_id FK "nullable — set only for CSV batch JEs"
        bigint accrual_plan_id FK "nullable — set only for plan-posted accruals"
        bigint cheque_id FK "nullable"
    }

    journal_lines {
        bigint id PK
        bigint entry_id FK
        bigint account_id FK
        bigint party_id FK "nullable"
        numeric amount
    }

    accrual_plans {
        bigint id PK
        text direction "revenue | expense"
        bigint party_id FK
        bigint target_account_id FK
    }

    accrual_obligations {
        bigint id PK
        bigint party_id FK
        bigint accrual_plan_id FK "nullable"
        bigint source_entry_id FK "accrual JE"
        bigint source_line_id FK "bridge line on accrual"
        text obligation_type "receivable | payable | unearned"
        text status
        numeric open_amount
    }

    settlement_allocations {
        bigint id PK
        bigint entry_id FK "settlement GL journal entry"
        bigint obligation_id FK
        numeric amount "applied to this obligation"
    }
```

Each journal entry must have **at least two lines** and **line amounts that sum to zero**; PostgreSQL enforces this at **transaction commit** via deferrable constraint triggers (migration `027`), in addition to application validation in `LedgerService`.

---

## Settlements are allocations grouped by `entry_id`

There is **no** separate settlement header table. A settlement is one or more **`settlement_allocations`** rows that share the same **`entry_id`** — the journal entry that carries the settlement GL (a dedicated settlement JE, the import row's JE once [#151](https://github.com/brettski74/TallyBadger/issues/151) lands, or the accrual JE after same-day collapse).

| Former `settlement_events` column | Where it lives now |
|-----------------------------------|-------------------|
| `party_id` | `accrual_obligations.party_id` (via each allocation) |
| `settlement_type` | Derived from `obligation_type` (`receivable` → receipt, `payable` → payment) |
| `event_date` | `journal_entries.entry_date` for `entry_id` |
| `cash_account_id` | Cash/bank **journal line** on `entry_id` |
| Total cash amount | **Not stored** on allocations — authoritative on journal lines |
| Per-obligation applied amount | `settlement_allocations.amount` |
| `entry_id` | **`settlement_allocations.entry_id`** (required FK) |

**Two amounts that matter:**

1. **Cash on the journal entry** (bank line magnitude) — from `journal_lines`.
2. **Applied to each obligation** — `settlement_allocations.amount` (sum may be **less** than cash on the entry when unapplied cash sits on other journal lines).

One bank movement closing multiple obligations → **multiple allocation rows**, same `entry_id`.

---

## Two ways journal entries enter the ledger

```mermaid
flowchart TB
    subgraph planPath [Accrual plan path]
        AP[accrual_plans] --> AJE[journal_entries<br/>accrual_plan_id set<br/>import_batch_id NULL]
        AJE --> JL1[journal_lines]
        AJE --> AO[accrual_obligations<br/>source_entry_id → accrual JE]
    end

    subgraph csvPath [CSV import batch path]
        IB[import_batches] --> IJE[journal_entries<br/>import_batch_id set<br/>accrual_plan_id NULL]
        IJE --> JL2[journal_lines]
    end

    AO -.->|settled via allocations| SA[settlement_allocations]
    IJE -.->|entry_id when #151 posts settlement| SA
    AJE -.->|entry_id after same-day collapse| SA
    SA --> AO
```

| Origin | Typical `journal_entries` marker | Creates `accrual_obligations`? |
|--------|----------------------------------|--------------------------------|
| **Accrual plan** (`create_accrual_plan`) | `accrual_plan_id` | **Yes** — one per scheduled accrual on the bridge line (ledger **A/R** for `revenue` plans, **A/P** for `expense` plans from settings at post time; [#235](https://github.com/brettski74/TallyBadger/issues/235)). |
| **CSV import** (`create_import_batch_with_entries`) | `import_batch_id` | **No** for plain cash/expense/revenue rows. **Yes** when **`line[]`** includes **`obligation-id`** — see [#151](https://github.com/brettski74/TallyBadger/issues/151). |

An obligation belongs to the **accrual subledger** (`accrual_obligations` + its `source_entry_id` accrual JE). A batch is only the set of journal entries tagged with that batch's `import_batch_id`.

---

## Settlement flow (manual today; CSV `line[]` in #151)

```mermaid
sequenceDiagram
    participant Author as Author / UI / CSV line[] (#151)
    participant API as Ledger service
    participant JE as journal_entries
    participant AO as accrual_obligations
    participant SA as settlement_allocations

    Note over Author,AO: Obligation already exists (from accrual plan)

    Author->>API: POST /settlements (manual) or line[] keys (#151)
    API->>AO: validate open_amount, type, party
    alt Same-day exact collapse (receipt)
        API->>JE: rewrite accrual lines (cash on accrual entry, reduce bridge)
        API->>SA: insert allocations (entry_id = accrual JE)
    else Normal settlement
        API->>JE: insert settlement JE (or use import JE from line[] #151)
        API->>SA: insert allocations (entry_id = that JE)
    end
    API->>AO: reduce open_amount, update status
```

**Manual vs CSV `line[]`:** same `settlement_allocations` / obligation updates. Manual **`POST /settlements`** may create a settlement journal entry or collapse into an accrual entry; CSV import supplies GL via **`line[]`** and reuses that entry (or collapses when eligible) ([#151](https://github.com/brettski74/TallyBadger/issues/151)).

---

## Import batch unload — discovery and scope

`DELETE /import-batches/{id}` (see `unload_import_batch` in `ledger/service.py`):

1. Collect `batch_entry_ids` = all `journal_entries` where `import_batch_id = batch`.
2. **Rollback settlements** by finding `settlement_allocations` where **`entry_id ∈ batch_entry_ids`**, then reversing obligation balances, journal line side effects (receipt/payment same-day collapse rewrites, early receipt/payment reclassification, unapplied unearned/prepaid lines), and deleting allocation rows.
3. **Delete obligations** whose source accrual line/entry is in the batch (batch-created obligations only).
4. **Delete** each batch journal entry (and reopen cheques if needed).
5. **Delete** the `import_batches` row.

```mermaid
flowchart LR
    subgraph batchScope [Owned by this CSV batch]
        IB[import_batches]
        IJE[journal_entries with import_batch_id]
        IJE --> JL[journal_lines]
        AO2[obligations whose source_entry_id is a batch JE]
    end

    subgraph outside [Typical plan obligation — not batch-owned]
        AJE[accrual journal_entries<br/>accrual_plan_id set]
        AO1[obligations from plans<br/>source → accrual JE]
    end

    IB --> IJE
    IJE -.->|settlement entry_id| SA[settlement_allocations]
    AO1 --> SA
    AO2 --> SA
```

### JE handling during settlement rollback

| `journal_entries` marker | On unload |
|--------------------------|-----------|
| `import_batch_id` set (batch JE) | Deleted with the batch (after allocation rollback). |
| `accrual_plan_id` set (plan accrual JE) | **Not deleted** — line mutations reversed; `import_batch_id` cleared if CSV import stamped it during collapse ([#151](https://github.com/brettski74/TallyBadger/issues/151)). |
| Neither (standalone settlement JE) | Deleted when not in `batch_entry_ids` and not a plan accrual. |

### What unload does *not* do (by design)

- **Delete accrual plan journal entries** or plan-created obligations (they are not batch-tagged).
- **Undo manual settlements** whose `entry_id` is not on a batch-tagged journal entry — there is no `DELETE /settlements` API.

Import unload is the **supported rollback path for CSV batch work**. Settlement rollback tests that exercise batch + settlement together belong with [#151](https://github.com/brettski74/TallyBadger/issues/151) / [#152](https://github.com/brettski74/TallyBadger/issues/152) once CSV settlement is implemented.

---

## Accrual plan list filters (`GET /accrual-plans`, #168)

The list endpoint returns `{ "plans": [...], "filter_options": null | {...} }`. Query parameters combine with **AND** semantics; omit a parameter for no constraint on that dimension.

| Parameter | Behaviour |
|-----------|-----------|
| `party_ids`, `target_account_ids` | Multi-value exact match on the plan row |
| `from_date`, `to_date` | Plan `[start_date, end_date]` overlaps the filter range (inclusive) |
| `name` | Case-insensitive POSIX regex (`~*`) on plan `name`; invalid pattern → **422** |
| `settlement_status` | `any` \| `unsettled` \| `open` \| `partially_settled` \| `settled` — plan-level buckets per [#159](https://github.com/brettski74/TallyBadger/issues/159). **Omitted = no filter** (same as `any`). The register UI defaults to `open` on first load. |
| `include_filter_options` | When `true`, adds `filter_options` with distinct `party_ids` and `target_account_ids` from **all** plans (for filter dropdowns), independent of the current filter. |

**Settlement buckets (plan level):**

- **unsettled** — no `settlement_allocations` on any obligation for the plan.
- **open** — at least one obligation with `status` not in `settled`/`reconciled` or `open_amount > 0`.
- **partially_settled** — at least one allocation on the plan’s obligations and the plan is not fully settled.
- **settled** — no obligation with non-terminal status and positive `open_amount` (plans with no obligations match vacuously).

---

## References

- Schema: `sql/007_settlement_workflow.sql`, `sql/024_settlement_allocations_entry_id.sql`, `sql/022_import_batches_and_journal_fk.sql`
- Posting: `LedgerService.record_settlement`, `create_import_batch_with_entries`, `unload_import_batch`
- Snapshot: [docs/backup-snapshot-format.md](backup-snapshot-format.md) (`format_version` **1.6.0** drops `settlement_events.json`)
