"""Complete snapshot export/import (JSON members in a ZIP). Issue #67 / #16."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from psycopg import Connection, sql
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

# FK-safe load order (#16); export uses the same ordering for stable diffs.
COMPLETE_TABLES: tuple[str, ...] = (
    "accounts",
    "parties",
    "party_match_patterns",
    "accrual_plans",
    "ledger_settings",
    "cel_rule_sets",
    "journal_entries",
    "journal_lines",
    "accrual_obligations",
    "settlement_events",
    "settlement_allocations",
    "import_templates",
)

DATE_COLUMNS = frozenset({"entry_date", "event_date", "start_date", "end_date"})
DECIMAL_COLUMNS = frozenset(
    {"amount", "original_amount", "open_amount"},
)
JSON_COLUMNS = frozenset({"definition", "columns_definition"})


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


def _assert_database_empty(conn: Connection) -> None:
    checks = [
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
    ]
    with conn.cursor() as cur:
        for table in checks:
            cur.execute(sql.SQL("SELECT COUNT(*) AS c FROM {}").format(sql.Identifier(table)))
            if int(cur.fetchone()["c"]) > 0:
                raise TargetNotEmptyError(
                    f"cannot import snapshot: table {table!r} is not empty "
                    "(restore only onto an empty data set; truncate first if appropriate)"
                )
        cur.execute("SELECT COUNT(*) AS c FROM ledger_settings")
        if int(cur.fetchone()["c"]) > 0:
            raise TargetNotEmptyError(
                "cannot import snapshot: ledger_settings already contains a row "
                "(restore only onto an empty data set; truncate first if appropriate)"
            )


def _fetch_table_rows(conn: Connection, table: str) -> list[dict[str, Any]]:
    q = sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(q)
        return [dict(r) for r in cur.fetchall()]


def export_complete_snapshot(conn: Connection) -> bytes:
    """Build a ZIP archive (UTF-8 JSON members) for export_type ``complete``."""
    schema_ver = current_schema_version(conn)
    exported_at = datetime.now(timezone.utc).isoformat()

    payloads: dict[str, bytes] = {}
    for table in COMPLETE_TABLES:
        rows = _fetch_table_rows(conn, table)
        raw = _rows_jsonable(rows)
        payloads[f"{table}.json"] = _canonical_json_bytes(raw)

    manifest: list[dict[str, str]] = []
    for path in sorted(payloads.keys()):
        manifest.append({"path": path, "sha256": _sha256_hex(payloads[path])})

    metadata_obj: dict[str, Any] = {
        "export_type": "complete",
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


def _validate_complete_payloads(payloads: dict[str, list[dict[str, Any]]]) -> None:
    for table in COMPLETE_TABLES:
        if table not in payloads:
            raise IncompleteSnapshotError(f"missing table file for {table!r}")
    _validate_journal(payloads["journal_lines"])


def import_complete_snapshot(conn: Connection, zip_bytes: bytes) -> None:
    """Import a ``complete`` snapshot into an **empty** database (data tables only)."""
    metadata, files = _load_zip_members(zip_bytes)

    export_type: Any = metadata.get("export_type")
    if export_type != "complete":
        raise IncompleteSnapshotError(
            f"this importer only supports export_type 'complete', not {export_type!r}"
        )

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
    for table in COMPLETE_TABLES:
        path = f"{table}.json"
        if path not in files:
            raise IncompleteSnapshotError(f"missing {path}")
        payloads[table] = _parse_table_file(path, files[path])

    _validate_complete_payloads(payloads)

    with conn.transaction():
        _assert_database_empty(conn)

        for table in COMPLETE_TABLES:
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
