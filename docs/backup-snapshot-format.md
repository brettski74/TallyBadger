# TallyBadger backup snapshot format

This document defines the **versioned ZIP snapshot** used for database backup and restore. It stays aligned with **`format_version`** in `metadata.json` (current export: **1.8.0**; prior archives remain importable per the version window in **[STYLE.md](../STYLE.md)**).

Parent product spec: GitHub issue [#16](https://github.com/brettski74/TallyBadger/issues/16). Slice 1 ([#67](https://github.com/brettski74/TallyBadger/issues/67)) shipped **complete** export/import; slice 2 ([#68](https://github.com/brettski74/TallyBadger/issues/68)) adds **`configuration`** and **`financial`** modes with scoped validation and duplicate policies.

## Container

- One **`.zip`** file per export.
- Table dumps are **UTF-8 JSON** at the archive root (`<table>.json`). From **`format_version` 1.1.0**, journal attachment blobs live under **`attachments/<id>.<ext>`** (extension from stored MIME; see below).
- **`metadata.json`** is required. It is **not** listed in `member_manifest` (see [Integrity](#integrity)).

## `metadata.json`

JSON object with at least:

| Field | Type | Description |
|-------|------|-------------|
| `export_type` | string | `complete`, `configuration`, or `financial` (see [Export modes](#export-modes)). |
| `format_version` | string | Snapshot layout version (semver string), e.g. `1.0.0`. |
| `schema_version` | string | `MAX(version)` from `schema_migrations` on the **source** database at export time. |
| `app_version` | string (optional) | TallyBadger package version string. |
| `exported_at` | string | ISO-8601 timestamp (UTC recommended). |
| `currency_assumption` | string | Documents single-currency numeric model; current value: `single_currency_numeric_18_2`. |
| `member_manifest` | array | Objects `{ "path": "<member>", "sha256": "<hex>" }` for **every** data member in the archive (each `*.json` table dump and, from **1.1.0** `complete` / `financial`, each `attachments/*` blob), not including `metadata.json`. |

Snapshot metadata does **not** include restore behaviour (no duplicate-resolution or policy flags). Export only records **what** was dumped; **how** to apply it on import is chosen per restore request in the API/UI.

### Version rules

- **`format_version`:** the implementation keeps an ordered **`FORMAT_VERSION_HISTORY`** (oldest → newest). **Import** accepts the **current** value (last entry) **and up to three prior** entries—four versions total when history is that long. Older archives outside that window fail with a clear error (see **[STYLE.md](../STYLE.md)**). **Export** always writes the newest history entry.
- **`schema_version` vs target:** import **succeeds** when the snapshot’s `schema_version` is a **version string that exists** in the target’s `schema_migrations` and the target’s `MAX(version)` is **not older** than that value (lexicographic order, same as export). So a backup taken at migration **015** can be restored on a database already at **016** (016 includes the 015 row). Import **fails** if the snapshot claims a **newer** schema than the target (upgrade the database first), or if the snapshot’s `schema_version` string **does not appear** in the target’s migration table (unknown or typo).

### `export_type` vs ZIP members

The set of data members (excluding `metadata.json`) must match **exactly** the matrix for **`export_type`** and **`format_version`**. For **1.0.0**, that set is only the table JSON files below (no attachments, no journal review messages). For **1.1.0** `complete` / `financial`, it is those JSON files **plus** one manifest entry per attachment row in `attachments.json` (binary path derived from attachment `id` and `mime_type`). From **1.2.0** `complete` / `financial`, **`journal_entry_review_messages.json`** is also required. From **1.3.0** `complete` / `financial`, **`cheques.json`** is also required (possibly an empty array). From **1.4.0** `complete` / `configuration`, **`journal_entry_filter_presets.json`** is also required (possibly an empty array); `financial`-only archives do **not** carry presets. From **1.5.0** `complete` / `financial`, **`import_batches.json`** is also required (possibly an empty array; loaded before `journal_entries` so `journal_entries.import_batch_id` can resolve). A mismatch fails import. The importer does **not** infer mode from files alone.

## Export modes

### `complete`

**Members:** the union of configuration and financial tables (see below). Same logical content as importing `configuration` then `financial` in two separate operations would require from the same source DB—**but** the product does not coordinate multi-step restores; each ZIP is one atomic import.

### `configuration`

**Includes:** `accounts`, `parties`, `party_match_patterns`, `ledger_settings`, `cel_rule_sets`, `import_templates`, from **`format_version` 1.4.0** also `journal_entry_filter_presets`, and from **`format_version` 1.8.0** also `cheque_register_filter_presets` ([#196](https://github.com/brettski74/TallyBadger/issues/196)). For **`format_version` < 1.7.0**, `accrual_plans` is also included here ([#157](https://github.com/brettski74/TallyBadger/issues/157)).

**Excludes:** `cheques`, `journal_entries`, `journal_lines`, `accrual_obligations`, `settlement_events`, `settlement_allocations`. From **1.7.0**, `accrual_plans` (moved to `financial`).

**Use:** chart of accounts, counterparties, CEL / import templates, ledger settings, and named journal-entry list filter presets—without posted history or subledger balances. Accrual **plans** and their posted entries ride together in **financial** / **complete** exports from **1.7.0** onward.

### `financial`

**Includes:** `journal_entries`, `journal_lines`, `accrual_obligations`, `settlement_allocations`, from **`format_version` 1.3.0** also `cheques` (loaded **before** `journal_entries` so `journal_entries.cheque_id` can resolve), from **1.5.0** also `import_batches` (loaded after `cheques` when present, and **before** `journal_entries` so `import_batch_id` can resolve), from **1.7.0** also `accrual_plans` (loaded after `import_batches` when present, and **before** `journal_entries` so `journal_entries.accrual_plan_id` and `accrual_obligations.accrual_plan_id` can resolve), from **1.2.0** also `journal_entry_review_messages`, and from **1.1.0** also `attachments`, `journal_entry_attachments`, plus **`attachments/*`** blob members listed in `member_manifest`. From **1.6.0**, **`settlement_events.json` is removed** — each row in `settlement_allocations.json` carries **`entry_id`** (FK to `journal_entries`). Archives with **`format_version` < 1.6.0** still include `settlement_events.json`; import normalizes them into allocations-only rows ([#153](https://github.com/brettski74/TallyBadger/issues/153)).

**Excludes:** configuration tables (`accounts`, `parties`, templates, settings, etc.). From **1.7.0**, `accrual_plans` is **not** excluded.

**Use:** GL activity, accrual plans (from **1.7.0**), obligation and settlement subledgers. **Does not** embed accounts or parties; those rows must **already exist** in the target database (for example after a separate `configuration` import), or every foreign key into those tables must resolve to pre-existing rows. From **1.7.0**, accrual plans referenced by journal entries and obligations are carried in the financial ZIP (same pattern as `import_batches` from **1.5.0**).

## Data members

Each included table is **`<table>.json`**: a **JSON array** of objects, one per row. Keys match **PostgreSQL column names** for that table, except **`attachments.json`** in **1.1.0** omits the **`blob`** column (bytes are stored only under **`attachments/`**).

### Load order (foreign-key safe)

Order for the **full** set (partial archives load only the files present, in this relative order):

1. `accounts.json`
2. `parties.json`
3. `party_match_patterns.json`
4. `accrual_plans.json` — **`format_version` < 1.7.0** configuration / complete only; from **1.7.0** financial / complete only (after `import_batches` when present).
5. `ledger_settings.json`
6. `cel_rule_sets.json`
7. `cheques.json` — **1.3.0** `complete` / `financial` only.
8. `import_batches.json` — **1.5.0** `complete` / `financial` only.
9. `journal_entries.json`
10. `journal_entry_review_messages.json` — **1.2.0** `complete` / `financial` only.
11. `journal_lines.json`
12. `accrual_obligations.json`
13. `settlement_events.json` — **only for `format_version` < 1.6.0** (import converts to allocations with `entry_id`).
14. `settlement_allocations.json` — from **1.6.0**, each row includes **`entry_id`**; older archives use `settlement_event_id` instead.
15. `attachments.json` — **1.1.0** `complete` / `financial` only (metadata columns; `blob` is filled from manifest-listed `attachments/*` members).
16. `journal_entry_attachments.json` — **1.1.0** `complete` / `financial` only.
17. `import_templates.json`
18. `journal_entry_filter_presets.json` — **1.4.0** `complete` / `configuration` only. The row's `definition` is a JSON object that round-trips the journal-entry filter dimensions; embedded `account_ids` and `party_ids` are validated against the archive's configuration members on import. Embedded `accrual_plan_ids` are validated against `accrual_plans.json` when that file is in the archive (**< 1.7.0** configuration / complete, or **≥ 1.7.0** complete / financial); for **≥ 1.7.0** configuration-only imports, `accrual_plan_ids` must resolve to **existing** `accrual_plans` rows in the target database.
19. `cheque_register_filter_presets.json` — **1.8.0** `complete` / `configuration` only. The row's `definition` round-trips cheque-register filter dimensions and sort keys; numeric `party_ids`, `credit_account_ids`, and `debit_account_ids` are validated against the archive's `parties` / `accounts` members on import (`party_ids` may include the literal token `"null"` for no party, which is not FK-validated). Sort fields are not FK-validated.

`ledger_settings` is exported as an array (typically one row with `id = 1`). New nullable columns may be added by later migrations (for example `default_cheque_credit_account_id` / `default_cheque_debit_account_id` at schema `020_*` for cheque last-used defaults, [#105](https://github.com/brettski74/TallyBadger/issues/105)); when present they are emitted as JSON `null` or an `accounts.id` integer and are validated as account foreign keys on import. Older archives that omit them remain importable into newer databases — the columns default to `NULL`.

**Binary paths:** `attachments/<id>.<ext>` where `<ext>` is `jpg` / `png` / `pdf` for common image/PDF MIME types, and `bin` otherwise (matches `tallybadger.attachments.mime_detect.mime_type_to_snapshot_extension`).

## Validation rules (import)

Imports run in a **single transaction** (atomic success or rollback). On entry, the importer runs **`SET CONSTRAINTS ALL DEFERRED`**. Snapshot application tables have **deferrable foreign keys** (**`DEFERRABLE INITIALLY IMMEDIATE`** via migration `015_snapshot_import_constraints_deferrable`). PostgreSQL’s `ALTER CONSTRAINT … DEFERRABLE` applies only to **foreign keys** here; `PRIMARY KEY`, `UNIQUE`, and `CHECK` constraints stay enforced per statement (duplicate keys and check violations still fail immediately unless recreated as deferrable). Normal traffic validates FKs **at the end of each statement**; only inside this import transaction are FKs deferred until **COMMIT**.

1. **Integrity:** manifest paths, SHA-256 hashes, and ZIP membership (see [Integrity](#integrity)).
2. **Shape:** every required table file for the `export_type` is present; each file is a JSON array of objects; columns coerced per [Type mapping](#type-mapping-postgresql--json--import).
3. **In-archive FKs:** for `complete` snapshots, foreign keys must resolve within the ZIP. For `configuration`, only configuration-table FKs are checked (all targets are in the same archive). For `financial`, FKs must resolve to rows **in the financial JSON** (e.g. `entry_id` on lines) or to **existing rows in the target database** for configuration entities (`account_id`, `party_id`, etc.). From **1.5.0**, non-null `journal_entries.import_batch_id` must reference a row in **`import_batches.json`** or an **existing** `import_batches` row in the target database. From **1.7.0**, non-null `accrual_plan_id` on journal entries and obligations must reference **`accrual_plans.json`** or an **existing** `accrual_plans` row in the target database (for archives **< 1.7.0**, plans are configuration-only and must already exist in the target DB). If a referenced `account_id` is neither in the archive nor in the database, import aborts with an explicit error (no multi-archive orchestration in the product).
4. **Journal:** if `journal_lines.json` is present, per-`entry_id` amounts must sum to **zero**.
5. **Restore mode** (API/UI **per import only** — not read from the ZIP):
   - **`abort` (default):** load in one transaction. The first failure from PostgreSQL (e.g. primary-key or unique violation, foreign-key violation) or from importer business rules (e.g. unbalanced journal) rolls back the whole import.
   - **`overwrite`:** before inserting, delete any **existing** rows whose primary key appears in the snapshot, in foreign-key **reverse** order within the snapshot’s table set. Then insert snapshot rows. If a delete fails because other rows still reference the target (e.g. configuration IDs still referenced by journals not in the snapshot), the import fails with an actionable error—use `erase_reload` with a **complete** snapshot, adjust data, or clear blocking rows first. Rows in the database that are **not** present in the snapshot are left unchanged (this is not a full mirror of the source unless the snapshot contained every row).
   - **`erase_reload`:** `TRUNCATE` all snapshot data tables (full application data wipe in FK-safe fashion), then load the archive. The database is empty of those rows before inserts; remaining FK or check failures imply a **bad or incomplete archive** for that path. **Not allowed** for `export_type: financial` (after a wipe there are no accounts/parties/plans for GL lines to reference). Use a **complete** or **configuration** snapshot, or import configuration then financial with another mode.

The application does **not** coordinate multi-step restores across requests; each import is one atomic transaction.

## Type mapping (PostgreSQL → JSON → import)

| PostgreSQL | JSON | Notes |
|------------|------|--------|
| `BIGINT`, `SMALLINT`, `INTEGER` | number | IDs and counts; importer coerces to int. |
| `NUMERIC(18,2)` | string | Decimal serialized as decimal string (e.g. `"250.00"`) for exact round-trip. |
| `TEXT` | string or `null` | |
| `BOOLEAN` | boolean | |
| `DATE` | string | ISO date `YYYY-MM-DD`. |
| `TIMESTAMPTZ` | string | ISO-8601; `Z` allowed; importer parses to timezone-aware datetimes. |
| `BYTEA` (fixed 32-octet digest) | string | Lowercase hex (64 hex characters), e.g. `import_batches.content_sha256` (**1.5.0**). |
| `JSONB` | object or array | Nested JSON (e.g. `cel_rule_sets.definition`, `import_templates.columns_definition`); no extra string encoding. |

`NULL` columns appear as JSON `null`.

## Integrity

- For each entry in `member_manifest`, the importer recomputes **SHA-256** over the **raw bytes** of that ZIP member (UTF-8 encoded JSON for `*.json` members; binary octets for `attachments/*`) and compares to `sha256`.
- The set of non-directory ZIP entries must be **exactly** `{ metadata.json } ∪ { path for each manifest entry }`. Extra or missing members cause a failed import. **Unknown or extra files are not ignored** — the archive must match the manifest and `export_type` exactly.

## Operator notes (edge cases)

- **Large archives:** export/import build the full ZIP in memory on the server. Very large databases mean longer requests and bigger downloads; reverse proxies or browsers may time out — raise timeouts if needed or use a stable network.
- **Optional table files:** for a given `export_type` and `format_version`, **every** table in that mode must appear in the ZIP (arrays may be empty). There are no optional JSON members within a mode.
- **Schema and format:** imports fail fast if `format_version` is unsupported or `schema_version` is incompatible with the target DB’s `schema_migrations` (see [Version rules](#version-rules)).

## Journal validation

For `journal_lines.json`, before insert the importer checks **double-entry balance**: for each `entry_id`, the sum of `amount` must be **zero**. Non-zero totals fail the import.

## Minimal examples (layout)

**`export_type: configuration`**, **`format_version` 1.4.0**

```text
metadata.json
accounts.json
parties.json
party_match_patterns.json
ledger_settings.json
cel_rule_sets.json
import_templates.json
journal_entry_filter_presets.json
```

**`export_type: financial`**, **`format_version` 1.0.0**

```text
metadata.json
journal_entries.json
journal_lines.json
accrual_obligations.json
settlement_events.json
settlement_allocations.json
```

**`export_type: financial`**, **`format_version` 1.1.0** — same JSON members as 1.0.0, plus `attachments.json` and `journal_entry_attachments.json`, plus zero or more **`attachments/<id>.<ext>`** files (each listed in `member_manifest`).

**`export_type: complete`**, **1.0.0** — union of configuration + financial 1.0.0 lists (twelve table JSON files).

**`export_type: complete`**, **1.1.0** — union of configuration JSON files + financial 1.1.0 JSON files + attachment blobs.

**`export_type: complete`**, **1.4.0** — adds `journal_entry_filter_presets.json` to the configuration members alongside the financial set from `format_version` 1.3.0 (cheques + journal review messages + attachment blobs).

**`export_type: financial`**, **`format_version` 1.5.0** — same members as **1.4.0** `financial`, plus **`import_batches.json`** (after `cheques.json` when cheques are in scope, before `journal_entries.json`).

**`export_type: complete`**, **1.5.0** — union of **1.5.0** `financial` members and **1.4.0** `configuration` members (including `journal_entry_filter_presets.json`).

**`export_type: financial`**, **`format_version` 1.6.0** — same members as **1.5.0** `financial`, but **`settlement_events.json` is omitted**; `settlement_allocations.json` rows include **`entry_id`**.

**`export_type: complete`**, **1.6.0** — union of **1.6.0** `financial` members and **1.4.0** `configuration` members (including `journal_entry_filter_presets.json`).

**`export_type: financial`**, **`format_version` 1.7.0** — same members as **1.6.0** `financial`, plus **`accrual_plans.json`** (after `import_batches.json` when present, before `journal_entries.json`).

**`export_type: configuration`**, **`format_version` 1.7.0** — same members as **1.4.0** `configuration` but **without** `accrual_plans.json`.

**`export_type: complete`**, **1.7.0** — union of **1.7.0** `financial` members and **1.7.0** `configuration` members (including `journal_entry_filter_presets.json`).

**`export_type: configuration`**, **`format_version` 1.8.0** — same members as **1.7.0** `configuration`, plus **`cheque_register_filter_presets.json`**.

**`export_type: complete`**, **1.8.0** — union of **1.8.0** `financial` members (same as **1.7.0** `financial`) and **1.8.0** `configuration` members (including `journal_entry_filter_presets.json` and `cheque_register_filter_presets.json`).

Example `accounts.json` snippet:

```json
[
  {"id":1,"name":"Cash","type":"asset","is_active":true,"created_at":"2026-01-03T12:00:00+00:00","updated_at":"2026-01-03T12:00:00+00:00"}
]
```

Integer and bigint columns export as JSON numbers; `NUMERIC` amounts export as JSON strings for exact decimals.

## API

- `POST /backup/export?export_type=complete|configuration|financial` — response body: `application/zip`. Default `export_type` is `complete`. Suggested download names: `tallybadger-complete-yyyymmdd-hhmmss.zip`, `tallybadger-config-…`, `tallybadger-financial-…` (local server time in `Content-Disposition`).
- `POST /backup/import` — `multipart/form-data`: field **`snapshot`** (ZIP file); field **`restore_mode`**: `abort` (default), `overwrite`, or `erase_reload`.

## Future

Encrypted ZIPs and additional duplicate modes remain **out of scope** unless specified in a later issue. Journal entry attachment backup/export/import is **`format_version` 1.1.0** ([#80](https://github.com/brettski74/TallyBadger/issues/80)).
