# TallyBadger backup snapshot format

This document defines the **versioned ZIP snapshot** used for database backup and restore. It stays aligned with **`format_version`** in `metadata.json` (currently **1.0.0**).

Parent product spec: GitHub issue [#16](https://github.com/brettski74/TallyBadger/issues/16). Slice 1 ([#67](https://github.com/brettski74/TallyBadger/issues/67)) shipped **complete** export/import; slice 2 ([#68](https://github.com/brettski74/TallyBadger/issues/68)) adds **`configuration`** and **`financial`** modes with scoped validation and duplicate policies.

## Container

- One **`.zip`** file per export.
- Text members are **UTF-8 JSON**. Paths are **flat** at the archive root (no directory prefixes).
- **`metadata.json`** is required. It is **not** listed in `member_manifest` (see [Integrity](#integrity)).

## `metadata.json`

JSON object with at least:

| Field | Type | Description |
|-------|------|-------------|
| `export_type` | string | `complete`, `configuration`, or `financial` (see [Export modes](#export-modes)). |
| `format_version` | string | Snapshot layout version (semver string), e.g. `1.0.0`. |
| `schema_version` | string | **Must equal** `MAX(version)` from `schema_migrations` on the source database at export time. |
| `app_version` | string (optional) | TallyBadger package version string. |
| `exported_at` | string | ISO-8601 timestamp (UTC recommended). |
| `currency_assumption` | string | Documents single-currency numeric model; current value: `single_currency_numeric_18_2`. |
| `member_manifest` | array | Objects `{ "path": "<file>.json", "sha256": "<hex>" }` for **every table JSON file** in the archive (not including `metadata.json`). |

### Version rules

- **Unsupported `format_version`:** import fails with a clear error.
- **`schema_version` mismatch:** import fails if the snapshot’s `schema_version` is not **exactly** equal to the target database’s `MAX(schema_migrations.version)`. Operators must run the same migrations on the target as on the source (or use a matching app release).

### `export_type` vs ZIP members

The set of `*.json` data members (excluding `metadata.json`) must match **exactly** the matrix for `export_type`. A mismatch (for example, `export_type: configuration` but `journal_entries.json` is present) fails import. The importer does **not** infer mode from files alone.

## Export modes

### `complete`

**Members:** the union of configuration and financial tables (see below). Same logical content as importing `configuration` then `financial` in two separate operations would require from the same source DB—**but** the product does not coordinate multi-step restores; each ZIP is one atomic import.

### `configuration`

**Includes:** `accounts`, `parties`, `party_match_patterns`, `accrual_plans`, `ledger_settings`, `cel_rule_sets`, `import_templates`.

**Excludes:** `journal_entries`, `journal_lines`, `accrual_obligations`, `settlement_events`, `settlement_allocations`.

**Use:** chart of accounts, counterparties, accrual **plan** definitions, CEL / import templates, and ledger settings—without posted history or subledger balances.

### `financial`

**Includes:** `journal_entries`, `journal_lines`, `accrual_obligations`, `settlement_events`, `settlement_allocations`.

**Excludes:** all configuration tables.

**Use:** GL activity plus obligation and settlement subledgers. **Does not** embed accounts, parties, or plans; those rows must **already exist** in the target database (for example after a separate `configuration` import), or every foreign key into those tables must resolve to pre-existing rows.

## Data members

Each included table is **`<table>.json`**: a **JSON array** of objects, one per row. Keys match **PostgreSQL column names** for that table.

### Load order (foreign-key safe)

Order for the **full** set (partial archives load only the files present, in this relative order):

1. `accounts.json`
2. `parties.json`
3. `party_match_patterns.json`
4. `accrual_plans.json`
5. `ledger_settings.json`
6. `cel_rule_sets.json`
7. `journal_entries.json`
8. `journal_lines.json`
9. `accrual_obligations.json`
10. `settlement_events.json`
11. `settlement_allocations.json`
12. `import_templates.json`

`ledger_settings` is exported as an array (typically one row with `id = 1`).

## Validation rules (import)

Imports run in a **single transaction** (atomic success or rollback).

1. **Integrity:** manifest paths, SHA-256 hashes, and ZIP membership (see [Integrity](#integrity)).
2. **Shape:** every required table file for the `export_type` is present; each file is a JSON array of objects; columns coerced per [Type mapping](#type-mapping-postgresql--json--import).
3. **In-archive FKs:** for `complete` snapshots, foreign keys must resolve within the ZIP. For `configuration`, only configuration-table FKs are checked (all targets are in the same archive). For `financial`, FKs must resolve to rows **in the financial JSON** (e.g. `entry_id` on lines) or to **existing rows in the target database** for configuration entities (`account_id`, `party_id`, `accrual_plan_id`, etc.). If a referenced `account_id` is neither in the archive nor in the database, import aborts with an explicit error (no multi-archive orchestration in the product).
4. **Journal:** if `journal_lines.json` is present, per-`entry_id` amounts must sum to **zero**.
5. **Duplicate policy** (API `duplicate_policy` form field):
   - **`abort` (default):** every table in the snapshot’s **scope** must be **empty** before insert. Otherwise import fails with **409** and a message naming the blocking table.
   - **`overwrite`:** tables in scope are cleared first, then rows are inserted. **Financial** scope uses `TRUNCATE … RESTART IDENTITY CASCADE` on the five financial tables. **Complete** scope truncates all snapshot tables (same family as a dev “full wipe”). **Configuration** scope deletes configuration rows in FK-safe order; if **financial** rows still reference configuration (e.g. `journal_lines.account_id`), deletion fails with a clear error—operators must clear or overwrite financial data first, or use an empty database.

The application does **not** prescribe operator workflows for pairing archives; each request is one atomic import.

## Type mapping (PostgreSQL → JSON → import)

| PostgreSQL | JSON | Notes |
|------------|------|--------|
| `BIGINT`, `SMALLINT`, `INTEGER` | number | IDs and counts; importer coerces to int. |
| `NUMERIC(18,2)` | string | Decimal serialized as decimal string (e.g. `"250.00"`) for exact round-trip. |
| `TEXT` | string or `null` | |
| `BOOLEAN` | boolean | |
| `DATE` | string | ISO date `YYYY-MM-DD`. |
| `TIMESTAMPTZ` | string | ISO-8601; `Z` allowed; importer parses to timezone-aware datetimes. |
| `JSONB` | object or array | Nested JSON (e.g. `cel_rule_sets.definition`, `import_templates.columns_definition`); no extra string encoding. |

`NULL` columns appear as JSON `null`.

## Integrity

- For each entry in `member_manifest`, the importer recomputes **SHA-256** over the **raw UTF-8 bytes** of that ZIP member and compares to `sha256`.
- The set of non-directory ZIP entries must be **exactly** `{ metadata.json } ∪ { path for each manifest entry }`. Extra or missing members cause a failed import.

## Journal validation

For `journal_lines.json`, before insert the importer checks **double-entry balance**: for each `entry_id`, the sum of `amount` must be **zero**. Non-zero totals fail the import.

## Minimal examples (layout)

**`export_type: configuration`**

```text
metadata.json
accounts.json
parties.json
party_match_patterns.json
accrual_plans.json
ledger_settings.json
cel_rule_sets.json
import_templates.json
```

**`export_type: financial`**

```text
metadata.json
journal_entries.json
journal_lines.json
accrual_obligations.json
settlement_events.json
settlement_allocations.json
```

**`export_type: complete`** — union of the two lists above (twelve table files).

Example `accounts.json` snippet:

```json
[
  {"id":1,"name":"Cash","type":"asset","is_active":true,"created_at":"2026-01-03T12:00:00+00:00","updated_at":"2026-01-03T12:00:00+00:00"}
]
```

Integer and bigint columns export as JSON numbers; `NUMERIC` amounts export as JSON strings for exact decimals.

## API

- `POST /backup/export?export_type=complete|configuration|financial` — response body: `application/zip`. Default `export_type` is `complete`.
- `POST /backup/import` — `multipart/form-data`: field **`snapshot`** (ZIP file); field **`duplicate_policy`**: `abort` (default) or `overwrite`.

## Future

Encrypted ZIPs, additional duplicate modes, and attachment payloads are **out of scope** for `format_version` **1.0.0** unless specified in a later issue.
