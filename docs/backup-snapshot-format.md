# TallyBadger backup snapshot format

This document defines the **versioned ZIP snapshot** used for full database backup and restore (`export_type: complete`). It stays aligned with **`format_version`** in `metadata.json` (currently **1.0.0**).

Parent product spec: GitHub issue [#16](https://github.com/brettski74/TallyBadger/issues/16). Slice 1 (issue [#67](https://github.com/brettski74/TallyBadger/issues/67)) implements **complete** export/import only.

## Container

- One **`.zip`** file per export.
- Text members are **UTF-8 JSON**. Paths are **flat** at the archive root (no directory prefixes).
- **`metadata.json`** is required. It is **not** listed in `member_manifest` (see [Integrity](#integrity)).

## `metadata.json`

JSON object with at least:

| Field | Type | Description |
|-------|------|-------------|
| `export_type` | string | `complete` for this slice (`configuration` / `financial` are reserved for later). |
| `format_version` | string | Snapshot layout version (semver string), e.g. `1.0.0`. |
| `schema_version` | string | **Must equal** `MAX(version)` from `schema_migrations` on the source database at export time. |
| `app_version` | string (optional) | TallyBadger package version string. |
| `exported_at` | string | ISO-8601 timestamp (UTC recommended). |
| `currency_assumption` | string | Documents single-currency numeric model; current value: `single_currency_numeric_18_2`. |
| `member_manifest` | array | Objects `{ "path": "<file>.json", "sha256": "<hex>" }` for **every table JSON file** in the archive (not including `metadata.json`). |

### Version rules

- **Unsupported `format_version`:** import fails with a clear error.
- **`schema_version` mismatch:** import fails if the snapshot’s `schema_version` is not **exactly** equal to the target database’s `MAX(schema_migrations.version)`. Operators must run the same migrations on the target as on the source (or use a matching app release).

## Data members (`complete`)

Each relational table is one **`<table>.json`** file: a **JSON array** of objects, one object per row. Keys match **PostgreSQL column names** for that table.

Load order (foreign-key safe):

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

## Minimal example (layout only)

```text
metadata.json
accounts.json
parties.json
party_match_patterns.json
accrual_plans.json
ledger_settings.json
cel_rule_sets.json
journal_entries.json
journal_lines.json
accrual_obligations.json
settlement_events.json
settlement_allocations.json
import_templates.json
```

Example `accounts.json` snippet:

```json
[
  {"id":1,"name":"Cash","type":"asset","is_active":true,"created_at":"2026-01-03T12:00:00+00:00","updated_at":"2026-01-03T12:00:00+00:00"}
]
```

Integer and bigint columns export as JSON numbers; `NUMERIC` amounts export as JSON strings for exact decimals.

## API

- `POST /backup/export` — response body: `application/zip` (complete snapshot).
- `POST /backup/import` — `multipart/form-data` field **`snapshot`**: ZIP file. Target database **data tables must be empty** (no configuration or financial rows); otherwise the API returns **409**.

## Future

- Partial exports (`configuration`, `financial`), encrypted ZIPs, and duplicate-key policies on non-empty targets are **out of scope** for format `1.0.0` / slice 1.
