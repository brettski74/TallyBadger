"""Snapshot export/import (JSON members in a ZIP). Issues #16, #67, #68."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from psycopg import Connection, sql
from psycopg import errors as pg_errors
from psycopg.types.json import Json

from tallybadger import __version__ as app_version
from tallybadger.backup.errors import (
    IncompleteSnapshotError,
    SchemaVersionMismatchError,
    SnapshotIntegrityError,
    SnapshotValidationError,
    TargetNotEmptyError,
    UnsupportedFormatVersionError,
)

FORMAT_VERSION = "1.0.0"
SUPPORTED_FORMAT_VERSIONS = frozenset({FORMAT_VERSION})

CURRENCY_ASSUMPTION = "single_currency_numeric_18_2"

ExportType = Literal["complete", "configuration", "financial"]

# FK-safe order (#16): configuration tables, then financial tables.
CONFIGURATION_TABLES: tuple[str, ...] = (
    "accounts",
    "parties",
    "party_match_patterns",
    "accrual_plans",
    "ledger_settings",
    "cel_rule_sets",
    "import_templates",
)

FINANCIAL_TABLES: tuple[str, ...] = (
    "journal_entries",
    "journal_lines",
    "accrual_obligations",
    "settlement_events",
    "settlement_allocations",
)

COMPLETE_TABLES: tuple[str, ...] = CONFIGURATION_TABLES + FINANCIAL_TABLES

SUPPORTED_EXPORT_TYPES: frozenset[str] = frozenset({"complete", "configuration", "financial"})

DATE_COLUMNS = frozenset({"entry_date", "event_date", "start_date", "end_date"})
DECIMAL_COLUMNS = frozenset(
    {"amount", "original_amount", "open_amount"},
)
JSON_COLUMNS = frozenset({"definition", "columns_definition"})


def tables_for_export_type(export_type: str) -> tuple[str, ...]:
    if export_type == "complete":
        return COMPLETE_TABLES
    if export_type == "configuration":
        return CONFIGURATION_TABLES
    if export_type == "financial":
        return FINANCIAL_TABLES
    raise IncompleteSnapshotError(
        f"export_type must be one of {sorted(SUPPORTED_EXPORT_TYPES)}, not {export_type!r}"
    )


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _cell_to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _rows_jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({k: _cell_to_jsonable(v) for k, v in row.items()})
    return out


def current_schema_version(conn: Connection) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        versions = [str(r["version"]) for r in cur.fetchall()]
    if not versions:
        raise RuntimeError("schema_migrations is empty")
    return max(versions)


def _existing_ids(conn: Connection, table: str) -> set[int]:
    q = sql.SQL("SELECT id FROM {}").format(sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(q)
        return {int(r["id"]) for r in cur.fetchall()}


def _assert_scope_empty_for_abort(conn: Connection, tables: tuple[str, ...]) -> None:
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(sql.SQL("SELECT COUNT(*) AS c FROM {}").format(sql.Identifier(table)))
            if int(cur.fetchone()["c"]) > 0:
                raise TargetNotEmptyError(
                    f"cannot import snapshot with duplicate_policy=abort: table {table!r} is not empty"
                )


def _truncate_complete_scope(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE TABLE
              import_templates,
              settlement_allocations,
              settlement_events,
              accrual_obligations,
              journal_lines,
              journal_entries,
              accrual_plans,
              party_match_patterns,
              parties,
              cel_rule_sets,
              ledger_settings,
              accounts
            RESTART IDENTITY CASCADE
            """
        )


def _truncate_financial_scope(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE TABLE
              settlement_allocations,
              settlement_events,
              accrual_obligations,
              journal_lines,
              journal_entries
            RESTART IDENTITY CASCADE
            """
        )


def _delete_configuration_scope(conn: Connection) -> None:
    """Remove configuration rows without CASCADE (fails if financial FKs still reference them)."""
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM import_templates")
            cur.execute("DELETE FROM cel_rule_sets")
            cur.execute("DELETE FROM ledger_settings")
            cur.execute("DELETE FROM accrual_plans")
            cur.execute("DELETE FROM party_match_patterns")
            cur.execute("DELETE FROM parties")
            cur.execute("DELETE FROM accounts")
    except pg_errors.ForeignKeyViolation as exc:
        raise SnapshotValidationError(
            "cannot replace configuration while financial rows still reference it "
            "(import financial snapshot with overwrite to clear activity first, "
            "or restore into a database without blocking journal/settlement rows). "
            f"Detail: {exc.diag.message_detail or exc}"
        ) from exc


def _clear_scope_for_overwrite(conn: Connection, export_type: str) -> None:
    if export_type == "complete":
        _truncate_complete_scope(conn)
    elif export_type == "financial":
        _truncate_financial_scope(conn)
    elif export_type == "configuration":
        _delete_configuration_scope(conn)
    else:
        raise IncompleteSnapshotError(f"unknown export_type {export_type!r}")


def _fetch_table_rows(conn: Connection, table: str) -> list[dict[str, Any]]:
    q = sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(q)
        return [dict(r) for r in cur.fetchall()]


def export_snapshot(conn: Connection, export_type: ExportType) -> bytes:
    """Build a ZIP archive (UTF-8 JSON members) for the given ``export_type``."""
    tables = tables_for_export_type(export_type)
    schema_ver = current_schema_version(conn)
    exported_at = datetime.now(timezone.utc).isoformat()

    payloads: dict[str, bytes] = {}
    for table in tables:
        rows = _fetch_table_rows(conn, table)
        raw = _rows_jsonable(rows)
        payloads[f"{table}.json"] = _canonical_json_bytes(raw)

    manifest: list[dict[str, str]] = []
    for path in sorted(payloads.keys()):
        manifest.append({"path": path, "sha256": _sha256_hex(payloads[path])})

    metadata_obj: dict[str, Any] = {
        "export_type": export_type,
        "format_version": FORMAT_VERSION,
        "schema_version": schema_ver,
        "app_version": app_version,
        "exported_at": exported_at,
        "currency_assumption": CURRENCY_ASSUMPTION,
        "member_manifest": manifest,
    }
    metadata_bytes = json.dumps(
        metadata_obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", metadata_bytes)
        for path in sorted(payloads.keys()):
            zf.writestr(path, payloads[path])
    return buf.getvalue()


def export_complete_snapshot(conn: Connection) -> bytes:
    """Build a ZIP for ``export_type: complete`` (backward-compatible name)."""
    return export_snapshot(conn, "complete")


def _parse_metadata(raw: bytes) -> dict[str, Any]:
    try:
        meta = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IncompleteSnapshotError("metadata.json is not valid UTF-8 JSON") from exc
    if not isinstance(meta, dict):
        raise IncompleteSnapshotError("metadata.json must be a JSON object")
    return meta


def _load_zip_members(zip_bytes: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise IncompleteSnapshotError("not a valid ZIP archive") from exc

    with zf:
        names = {n for n in zf.namelist() if not n.endswith("/")}
        if "metadata.json" not in names:
            raise IncompleteSnapshotError("metadata.json is missing from archive")

        metadata = _parse_metadata(zf.read("metadata.json"))
        manifest = metadata.get("member_manifest")
        if not isinstance(manifest, list):
            raise IncompleteSnapshotError("metadata.member_manifest must be a list")

        manifest_paths: set[str] = set()
        for item in manifest:
            if not isinstance(item, dict):
                raise IncompleteSnapshotError("member_manifest entries must be objects")
            path = item.get("path")
            digest = item.get("sha256")
            if not isinstance(path, str) or not isinstance(digest, str):
                raise IncompleteSnapshotError("member_manifest items need path and sha256 strings")
            manifest_paths.add(path)
            if path not in names:
                raise IncompleteSnapshotError(f"ZIP is missing member {path!r} listed in manifest")
            body = zf.read(path)
            if _sha256_hex(body) != digest.lower():
                raise SnapshotIntegrityError(f"SHA-256 mismatch for {path!r}")

        expected = manifest_paths | {"metadata.json"}
        if names != expected:
            extra = names - expected
            missing = expected - names
            msg_parts = []
            if extra:
                msg_parts.append(f"unexpected ZIP members: {sorted(extra)}")
            if missing:
                msg_parts.append(f"missing ZIP members: {sorted(missing)}")
            raise SnapshotIntegrityError("; ".join(msg_parts))

        files = {n: zf.read(n) for n in names if n != "metadata.json"}
    return metadata, files


def _parse_table_file(path: str, raw: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IncompleteSnapshotError(f"{path} is not valid UTF-8 JSON") from exc
    if not isinstance(data, list):
        raise IncompleteSnapshotError(f"{path} must be a JSON array of row objects")
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise IncompleteSnapshotError(f"{path} row {i} must be a JSON object")
    return data


def _coerce_cell(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in JSON_COLUMNS:
        return Json(value)
    if column in DATE_COLUMNS:
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise SnapshotValidationError(f"expected ISO date string for {column!r}")
    if column.endswith("_at"):
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise SnapshotValidationError(f"expected ISO datetime string for {column!r}")
    if column in DECIMAL_COLUMNS:
        return Decimal(str(value))
    if column.endswith("_id") or column == "id":
        return int(value)
    if column in (
        "is_active",
        "requires_review",
        "has_header_row",
        "business_day_adjust",
    ):
        return bool(value)
    if column in ("day_of_week", "day_of_month", "month_of_year", "sort_order"):
        return int(value) if value is not None else None
    return value


def _prepare_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    _ = table
    return {k: _coerce_cell(k, v) for k, v in row.items()}


def _validate_journal(lines: list[dict[str, Any]]) -> None:
    by_entry: dict[int, Decimal] = {}
    for line in lines:
        eid = int(line["entry_id"])
        amt = Decimal(str(line["amount"]))
        by_entry[eid] = by_entry.get(eid, Decimal("0")) + amt
    bad = {eid: total for eid, total in by_entry.items() if total != 0}
    if bad:
        raise SnapshotValidationError(
            "journal lines are not balanced per entry for entry_id(s): "
            + ", ".join(str(k) for k in sorted(bad.keys()))
        )


def _validate_payloads_for_tables(
    tables: tuple[str, ...],
    payloads: dict[str, list[dict[str, Any]]],
) -> None:
    for table in tables:
        if table not in payloads:
            raise IncompleteSnapshotError(f"missing table file for {table!r}")
    if "journal_lines" in payloads:
        _validate_journal(payloads["journal_lines"])


def _validate_configuration_fks(
    payloads: dict[str, list[dict[str, Any]]],
) -> None:
    acct = {int(r["id"]) for r in payloads["accounts"]}
    party = {int(r["id"]) for r in payloads["parties"]}
    plans = {int(r["id"]) for r in payloads["accrual_plans"]}
    cel = {int(r["id"]) for r in payloads["cel_rule_sets"]}

    for i, row in enumerate(payloads["party_match_patterns"]):
        pid = row.get("party_id")
        if pid is not None and int(pid) not in party:
            raise SnapshotValidationError(
                f"party_match_patterns[{i}] party_id={pid} has no matching row in parties.json"
            )

    for i, row in enumerate(payloads["parties"]):
        for col in ("default_revenue_account_id", "default_expense_account_id"):
            v = row.get(col)
            if v is not None and int(v) not in acct:
                raise SnapshotValidationError(
                    f"parties[{i}] {col}={v} has no matching row in accounts.json"
                )

    for i, row in enumerate(payloads["accrual_plans"]):
        if int(row["party_id"]) not in party:
            raise SnapshotValidationError(
                f"accrual_plans[{i}] party_id={row['party_id']} has no matching row in parties.json"
            )
        if int(row["target_account_id"]) not in acct:
            raise SnapshotValidationError(
                f"accrual_plans[{i}] target_account_id={row['target_account_id']} "
                "has no matching row in accounts.json"
            )
        if int(row["bridge_account_id"]) not in acct:
            raise SnapshotValidationError(
                f"accrual_plans[{i}] bridge_account_id={row['bridge_account_id']} "
                "has no matching row in accounts.json"
            )

    account_cols = (
        "accounts_receivable_account_id",
        "accounts_payable_account_id",
        "unearned_revenue_account_id",
        "unallocated_debits_account_id",
        "unallocated_credits_account_id",
    )
    for i, row in enumerate(payloads["ledger_settings"]):
        for col in account_cols:
            v = row.get(col)
            if v is not None and int(v) not in acct:
                raise SnapshotValidationError(
                    f"ledger_settings[{i}] {col}={v} has no matching row in accounts.json"
                )

    for i, row in enumerate(payloads["import_templates"]):
        crs = row.get("cel_rule_set_id")
        if crs is not None and int(crs) not in cel:
            raise SnapshotValidationError(
                f"import_templates[{i}] cel_rule_set_id={crs} has no matching row in cel_rule_sets.json"
            )
        dia = row.get("default_import_account_id")
        if dia is not None and int(dia) not in acct:
            raise SnapshotValidationError(
                f"import_templates[{i}] default_import_account_id={dia} "
                "has no matching row in accounts.json"
            )


def _validate_complete_fk_graph(payloads: dict[str, list[dict[str, Any]]]) -> None:
    """All FK targets appear in this archive (complete export)."""
    _validate_configuration_fks(payloads)

    acct = {int(r["id"]) for r in payloads["accounts"]}
    party = {int(r["id"]) for r in payloads["parties"]}
    plans = {int(r["id"]) for r in payloads["accrual_plans"]}
    je = {int(r["id"]) for r in payloads["journal_entries"]}
    jl = {int(r["id"]) for r in payloads["journal_lines"]}
    ao = {int(r["id"]) for r in payloads["accrual_obligations"]}
    se = {int(r["id"]) for r in payloads["settlement_events"]}

    for i, row in enumerate(payloads["journal_entries"]):
        ap = row.get("accrual_plan_id")
        if ap is not None and int(ap) not in plans:
            raise SnapshotValidationError(
                f"journal_entries[{i}] accrual_plan_id={ap} has no matching row in accrual_plans.json"
            )

    for i, row in enumerate(payloads["journal_lines"]):
        if int(row["entry_id"]) not in je:
            raise SnapshotValidationError(
                f"journal_lines[{i}] entry_id={row['entry_id']} has no matching row in journal_entries.json"
            )
        if int(row["account_id"]) not in acct:
            raise SnapshotValidationError(
                f"journal_lines[{i}] account_id={row['account_id']} has no matching row in accounts.json"
            )
        pid = row.get("party_id")
        if pid is not None and int(pid) not in party:
            raise SnapshotValidationError(
                f"journal_lines[{i}] party_id={pid} has no matching row in parties.json"
            )

    for i, row in enumerate(payloads["accrual_obligations"]):
        if int(row["party_id"]) not in party:
            raise SnapshotValidationError(
                f"accrual_obligations[{i}] party_id={row['party_id']} has no matching row in parties.json"
            )
        ap = row.get("accrual_plan_id")
        if ap is not None and int(ap) not in plans:
            raise SnapshotValidationError(
                f"accrual_obligations[{i}] accrual_plan_id={ap} has no matching row in accrual_plans.json"
            )
        se_id = row.get("source_entry_id")
        if se_id is not None and int(se_id) not in je:
            raise SnapshotValidationError(
                f"accrual_obligations[{i}] source_entry_id={se_id} "
                "has no matching row in journal_entries.json"
            )
        sl_id = row.get("source_line_id")
        if sl_id is not None and int(sl_id) not in jl:
            raise SnapshotValidationError(
                f"accrual_obligations[{i}] source_line_id={sl_id} "
                "has no matching row in journal_lines.json"
            )

    for i, row in enumerate(payloads["settlement_events"]):
        if int(row["party_id"]) not in party:
            raise SnapshotValidationError(
                f"settlement_events[{i}] party_id={row['party_id']} has no matching row in parties.json"
            )
        if int(row["cash_account_id"]) not in acct:
            raise SnapshotValidationError(
                f"settlement_events[{i}] cash_account_id={row['cash_account_id']} "
                "has no matching row in accounts.json"
            )
        if int(row["entry_id"]) not in je:
            raise SnapshotValidationError(
                f"settlement_events[{i}] entry_id={row['entry_id']} "
                "has no matching row in journal_entries.json"
            )

    for i, row in enumerate(payloads["settlement_allocations"]):
        if int(row["settlement_event_id"]) not in se:
            raise SnapshotValidationError(
                f"settlement_allocations[{i}] settlement_event_id={row['settlement_event_id']} "
                "has no matching row in settlement_events.json"
            )
        if int(row["obligation_id"]) not in ao:
            raise SnapshotValidationError(
                f"settlement_allocations[{i}] obligation_id={row['obligation_id']} "
                "has no matching row in accrual_obligations.json"
            )


def _validate_financial_fks(
    conn: Connection,
    payloads: dict[str, list[dict[str, Any]]],
) -> None:
    """Financial rows reference configuration entities that must already exist in the target DB."""
    acct_db = _existing_ids(conn, "accounts")
    party_db = _existing_ids(conn, "parties")
    plan_db = _existing_ids(conn, "accrual_plans")

    je = {int(r["id"]) for r in payloads["journal_entries"]}
    jl = {int(r["id"]) for r in payloads["journal_lines"]}
    ao = {int(r["id"]) for r in payloads["accrual_obligations"]}
    se = {int(r["id"]) for r in payloads["settlement_events"]}

    for i, row in enumerate(payloads["journal_entries"]):
        ap = row.get("accrual_plan_id")
        if ap is not None and int(ap) not in plan_db:
            raise SnapshotValidationError(
                f"journal_entries[{i}] accrual_plan_id={ap} not found in target database "
                "(financial snapshots do not include accrual_plans; import configuration first "
                "or fix the snapshot)."
            )

    for i, row in enumerate(payloads["journal_lines"]):
        if int(row["entry_id"]) not in je:
            raise SnapshotValidationError(
                f"journal_lines[{i}] entry_id={row['entry_id']} has no matching row in journal_entries.json"
            )
        if int(row["account_id"]) not in acct_db:
            raise SnapshotValidationError(
                f"journal_lines[{i}] account_id={row['account_id']} not found in target database "
                "(financial snapshots do not include accounts; import configuration first or fix the snapshot)."
            )
        pid = row.get("party_id")
        if pid is not None and int(pid) not in party_db:
            raise SnapshotValidationError(
                f"journal_lines[{i}] party_id={pid} not found in target database "
                "(financial snapshots do not include parties; import configuration first or fix the snapshot)."
            )

    for i, row in enumerate(payloads["accrual_obligations"]):
        if int(row["party_id"]) not in party_db:
            raise SnapshotValidationError(
                f"accrual_obligations[{i}] party_id={row['party_id']} not found in target database."
            )
        ap = row.get("accrual_plan_id")
        if ap is not None and int(ap) not in plan_db:
            raise SnapshotValidationError(
                f"accrual_obligations[{i}] accrual_plan_id={ap} not found in target database."
            )
        se_id = row.get("source_entry_id")
        if se_id is not None and int(se_id) not in je:
            raise SnapshotValidationError(
                f"accrual_obligations[{i}] source_entry_id={se_id} "
                "has no matching row in journal_entries.json"
            )
        sl_id = row.get("source_line_id")
        if sl_id is not None and int(sl_id) not in jl:
            raise SnapshotValidationError(
                f"accrual_obligations[{i}] source_line_id={sl_id} "
                "has no matching row in journal_lines.json"
            )

    for i, row in enumerate(payloads["settlement_events"]):
        if int(row["party_id"]) not in party_db:
            raise SnapshotValidationError(
                f"settlement_events[{i}] party_id={row['party_id']} not found in target database."
            )
        if int(row["cash_account_id"]) not in acct_db:
            raise SnapshotValidationError(
                f"settlement_events[{i}] cash_account_id={row['cash_account_id']} not found in target database."
            )
        if int(row["entry_id"]) not in je:
            raise SnapshotValidationError(
                f"settlement_events[{i}] entry_id={row['entry_id']} "
                "has no matching row in journal_entries.json"
            )

    for i, row in enumerate(payloads["settlement_allocations"]):
        if int(row["settlement_event_id"]) not in se:
            raise SnapshotValidationError(
                f"settlement_allocations[{i}] settlement_event_id={row['settlement_event_id']} "
                "has no matching row in settlement_events.json"
            )
        if int(row["obligation_id"]) not in ao:
            raise SnapshotValidationError(
                f"settlement_allocations[{i}] obligation_id={row['obligation_id']} "
                "has no matching row in accrual_obligations.json"
            )


def _assert_manifest_matches_export_type(metadata: dict[str, Any], export_type: str) -> None:
    tables = tables_for_export_type(export_type)
    expected = {f"{t}.json" for t in tables}
    manifest = metadata.get("member_manifest")
    if not isinstance(manifest, list):
        return
    paths = {item["path"] for item in manifest if isinstance(item, dict) and "path" in item}
    if paths != expected:
        raise IncompleteSnapshotError(
            f"archive member set {sorted(paths)!r} does not match export_type {export_type!r} "
            f"(expected {sorted(expected)!r})"
        )


def import_snapshot(
    conn: Connection,
    zip_bytes: bytes,
    *,
    duplicate_policy: str = "abort",
) -> None:
    """Import a snapshot; tables loaded are exactly those declared by ``export_type`` in metadata."""
    pol = duplicate_policy.strip().lower()
    if pol not in ("abort", "overwrite"):
        raise IncompleteSnapshotError(
            f"duplicate_policy must be 'abort' or 'overwrite', not {duplicate_policy!r}"
        )

    metadata, files = _load_zip_members(zip_bytes)

    export_type_raw: Any = metadata.get("export_type")
    if not isinstance(export_type_raw, str):
        raise IncompleteSnapshotError("metadata.export_type must be a string")
    export_type = export_type_raw
    if export_type not in SUPPORTED_EXPORT_TYPES:
        raise IncompleteSnapshotError(
            f"unsupported export_type {export_type!r}; expected one of {sorted(SUPPORTED_EXPORT_TYPES)}"
        )

    _assert_manifest_matches_export_type(metadata, export_type)
    tables = tables_for_export_type(export_type)

    fmt: Any = metadata.get("format_version")
    if fmt not in SUPPORTED_FORMAT_VERSIONS:
        raise UnsupportedFormatVersionError(
            f"unsupported format_version {fmt!r}; this release supports {sorted(SUPPORTED_FORMAT_VERSIONS)}"
        )

    snap_schema: Any = metadata.get("schema_version")
    if not isinstance(snap_schema, str):
        raise IncompleteSnapshotError("metadata.schema_version must be a string")

    db_schema = current_schema_version(conn)
    if snap_schema != db_schema:
        raise SchemaVersionMismatchError(
            f"snapshot schema_version {snap_schema!r} does not match database "
            f"schema_migrations ({db_schema!r}); apply the same migrations as the "
            "source system or use a matching app release"
        )

    payloads: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        path = f"{table}.json"
        if path not in files:
            raise IncompleteSnapshotError(f"missing {path}")
        payloads[table] = _parse_table_file(path, files[path])

    _validate_payloads_for_tables(tables, payloads)

    if export_type == "complete":
        _validate_complete_fk_graph(payloads)
    elif export_type == "configuration":
        _validate_configuration_fks(payloads)
    else:
        _validate_financial_fks(conn, payloads)

    with conn.transaction():
        if pol == "abort":
            _assert_scope_empty_for_abort(conn, tables)
        else:
            _clear_scope_for_overwrite(conn, export_type)

        for table in tables:
            rows = [_prepare_row(table, r) for r in payloads[table]]
            if not rows:
                continue
            cols = list(rows[0].keys())
            for r in rows[1:]:
                if list(r.keys()) != cols:
                    raise SnapshotValidationError(
                        f"inconsistent columns in {table!r} rows (all rows must share the same keys)"
                    )

            identifiers = [sql.Identifier(c) for c in cols]
            placeholders = sql.SQL(", ").join(sql.Placeholder(c) for c in cols)

            insert = sql.SQL("INSERT INTO {table} ({fields}) VALUES ({vals})").format(
                table=sql.Identifier(table),
                fields=sql.SQL(", ").join(identifiers),
                vals=placeholders,
            )

            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(insert, row)

        _resync_serials(conn)


def import_complete_snapshot(
    conn: Connection,
    zip_bytes: bytes,
    *,
    duplicate_policy: str = "abort",
) -> None:
    """Import a ``complete`` snapshot (backward-compatible entry point)."""
    import_snapshot(conn, zip_bytes, duplicate_policy=duplicate_policy)


def _resync_serials(conn: Connection) -> None:
    for table in (
        "accounts",
        "parties",
        "party_match_patterns",
        "accrual_plans",
        "cel_rule_sets",
        "journal_entries",
        "journal_lines",
        "accrual_obligations",
        "settlement_events",
        "settlement_allocations",
        "import_templates",
    ):
        stmt = sql.SQL(
            "SELECT setval(pg_get_serial_sequence({tbl}, 'id'), "
            "COALESCE((SELECT MAX(id) FROM {ident}), 1), true)"
        ).format(tbl=sql.Literal(table), ident=sql.Identifier(table))
        with conn.cursor() as cur:
            cur.execute(stmt)


def snapshot_table_counts(conn: Connection) -> dict[str, int]:
    """Return row counts for snapshot tables (for tests / diagnostics)."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in COMPLETE_TABLES:
            cur.execute(sql.SQL("SELECT COUNT(*) AS c FROM {}").format(sql.Identifier(table)))
            counts[table] = int(cur.fetchone()["c"])
    return counts
