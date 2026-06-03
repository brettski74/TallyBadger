"""Snapshot export/import (ZIP legacy, tar.gz ``2.0.0``). Issues #16, #67, #68, #251, #252."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from collections.abc import Iterator
from typing import Any, BinaryIO, Literal

SnapshotContainer = Literal["zip", "gzip"]

from psycopg import Connection, sql
from psycopg import errors as pg_errors
from psycopg.types.json import Json

from tallybadger import __version__ as app_version
from tallybadger.attachments.mime_detect import mime_type_to_snapshot_extension
from tallybadger.backup.errors import (
    IncompleteSnapshotError,
    SchemaVersionMismatchError,
    SnapshotIntegrityError,
    SnapshotValidationError,
    UnsupportedFormatVersionError,
)
from tallybadger.backup.restore_mode import resolve_restore_mode

# Semver-ordered, oldest first. When the on-wire layout changes, append a new version
# (see docs/backup-snapshot-format.md). Import accepts the last four entries (STYLE.md).
FORMAT_VERSION_HISTORY: tuple[str, ...] = (
    "1.0.0",
    "1.1.0",
    "1.2.0",
    "1.3.0",
    "1.4.0",
    "1.5.0",
    "1.6.0",
    "1.7.0",
    "1.8.0",
    "2.0.0",
    "2.1.0",
)


def export_format_version() -> str:
    """``format_version`` written to new snapshot exports."""
    return FORMAT_VERSION_HISTORY[-1]


def supported_import_format_versions() -> frozenset[str]:
    """``format_version`` values accepted on import (current plus up to three prior)."""
    return frozenset(FORMAT_VERSION_HISTORY[-4:])


def oldest_supported_import_format_version() -> str:
    """Minimum ``format_version`` in the import window (semver order)."""
    return min(supported_import_format_versions(), key=_format_version_tuple)


def format_deprecation_warning(archive_format_version: str) -> str | None:
    """Operator message after a successful import of an older supported snapshot format (#202).

    Returns ``None`` when the archive uses the current export ``format_version``.
    """
    current = export_format_version()
    if _format_version_tuple(archive_format_version) >= _format_version_tuple(current):
        return None
    oldest = oldest_supported_import_format_version()
    return (
        f"This backup uses snapshot format version {archive_format_version}. "
        f"The current export format for this TallyBadger release is {current}. "
        f"The oldest format version still supported for import is {oldest}. "
        f"Support for format {archive_format_version} is deprecated and will be removed "
        f"in a future release. Re-export from a database on the current release is "
        f"recommended to ensure continued support."
    )


CURRENCY_ASSUMPTION = "single_currency_numeric_18_2"

ExportType = Literal["complete", "configuration", "financial"]

# FK-safe order (#16): configuration tables, then financial tables.
# ``journal_entry_filter_presets`` (format_version ≥ 1.4.0) appended last; its JSONB
# definition references account/party/accrual_plan ids that are validated separately
# against the rest of the configuration scope, but the table has no FK constraints
# so its load position is otherwise free.
CONFIGURATION_TABLES_BASE: tuple[str, ...] = (
    "accounts",
    "parties",
    "party_match_patterns",
    "ledger_settings",
    "cel_rule_sets",
    "import_templates",
)

JOURNAL_ENTRY_FILTER_PRESET_TABLE = "journal_entry_filter_presets"
CHEQUE_REGISTER_FILTER_PRESET_TABLE = "cheque_register_filter_presets"

# Journal entry attachment metadata + links (``format_version`` ≥ 1.1.0, complete/financial only).
ATTACHMENT_SNAPSHOT_TABLES: tuple[str, ...] = ("attachments", "journal_entry_attachments")

SUPPORTED_EXPORT_TYPES: frozenset[str] = frozenset({"complete", "configuration", "financial"})

# Import-time only (never stored in snapshot metadata).
RestoreMode = Literal["abort", "overwrite", "erase-reload"]
SUPPORTED_RESTORE_MODES: frozenset[str] = frozenset({"abort", "overwrite", "erase-reload"})

DATE_COLUMNS = frozenset({"entry_date", "event_date", "start_date", "end_date"})
DECIMAL_COLUMNS = frozenset(
    {"amount", "original_amount", "open_amount"},
)
JSON_COLUMNS = frozenset({"definition", "columns_definition"})


def _format_version_tuple(version: str) -> tuple[int, ...]:
    parts = version.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError as exc:
        raise IncompleteSnapshotError(f"invalid format_version semver: {version!r}") from exc


def snapshot_includes_attachment_tables(format_version: str) -> bool:
    """Attachment JSON + ``attachments/*`` blobs apply for ``format_version`` ≥ 1.1.0."""
    return _format_version_tuple(format_version) >= (1, 1, 0)


def snapshot_includes_filter_presets(format_version: str) -> bool:
    """``journal_entry_filter_presets.json`` applies for ``format_version`` ≥ 1.4.0."""
    return _format_version_tuple(format_version) >= (1, 4, 0)


def snapshot_includes_cheque_register_filter_presets(format_version: str) -> bool:
    """``cheque_register_filter_presets.json`` applies for ``format_version`` ≥ 1.8.0."""
    return _format_version_tuple(format_version) >= (1, 8, 0)


def snapshot_includes_import_batches(format_version: str) -> bool:
    """``import_batches.json`` applies for ``format_version`` ≥ 1.5.0 (``complete`` / ``financial``)."""
    return _format_version_tuple(format_version) >= (1, 5, 0)


def snapshot_includes_settlement_events(format_version: str) -> bool:
    """``settlement_events.json`` applies for ``format_version`` < 1.6.0 (removed in #153)."""
    return _format_version_tuple(format_version) < (1, 6, 0)


def snapshot_includes_accrual_plans_in_financial(format_version: str) -> bool:
    """``accrual_plans.json`` is a financial member for ``format_version`` ≥ 1.7.0 (#157)."""
    return _format_version_tuple(format_version) >= (1, 7, 0)


def configuration_tables_for_format(format_version: str) -> tuple[str, ...]:
    """Configuration snapshot members for ``format_version`` (base ± preset sidecars)."""
    parts: list[str] = list(CONFIGURATION_TABLES_BASE)
    if not snapshot_includes_accrual_plans_in_financial(format_version):
        idx = parts.index("party_match_patterns") + 1
        parts.insert(idx, "accrual_plans")
    if snapshot_includes_filter_presets(format_version):
        parts.append(JOURNAL_ENTRY_FILTER_PRESET_TABLE)
    if snapshot_includes_cheque_register_filter_presets(format_version):
        parts.append(CHEQUE_REGISTER_FILTER_PRESET_TABLE)
    return tuple(parts)


# Configuration tables for the **newest** export (always includes the preset sidecar
# once ``format_version`` ≥ 1.4.0). Callers that need a format-aware list should
# prefer :func:`configuration_tables_for_format`.
CONFIGURATION_TABLES: tuple[str, ...] = configuration_tables_for_format(
    FORMAT_VERSION_HISTORY[-1],
)


def financial_tables_core(format_version: str) -> tuple[str, ...]:
    """Journal-related tables in load order (parents before dependents where required)."""
    parts: list[str] = []
    if _format_version_tuple(format_version) >= (1, 3, 0):
        parts.append("cheques")
    if snapshot_includes_import_batches(format_version):
        parts.append("import_batches")
    if snapshot_includes_accrual_plans_in_financial(format_version):
        parts.append("accrual_plans")
    parts.append("journal_entries")
    if _format_version_tuple(format_version) >= (1, 2, 0):
        parts.append("journal_entry_review_messages")
    parts.extend(
        [
            "journal_lines",
            "accrual_obligations",
        ],
    )
    if snapshot_includes_settlement_events(format_version):
        parts.append("settlement_events")
    parts.append("settlement_allocations")
    return tuple(parts)


def financial_tables_for_format(format_version: str) -> tuple[str, ...]:
    """Financial snapshot members for ``format_version`` (core ± attachment sidecars)."""
    core = financial_tables_core(format_version)
    if snapshot_includes_attachment_tables(format_version):
        return core + ATTACHMENT_SNAPSHOT_TABLES
    return core


COMPLETE_TABLES: tuple[str, ...] = CONFIGURATION_TABLES + financial_tables_for_format(
    export_format_version(),
)


def tables_for_import(export_type: str, format_version: str) -> tuple[str, ...]:
    """Table JSON members expected for this ``export_type`` and archive ``format_version``."""
    cfg = configuration_tables_for_format(format_version)
    if export_type == "configuration":
        return cfg
    fin = financial_tables_for_format(format_version)
    if export_type == "financial":
        return fin
    if export_type == "complete":
        return cfg + fin
    raise IncompleteSnapshotError(
        f"export_type must be one of {sorted(SUPPORTED_EXPORT_TYPES)}, not {export_type!r}"
    )


def tables_for_export_type(export_type: str) -> tuple[str, ...]:
    """Tables included in a **new** export (always the newest ``format_version``)."""
    return tables_for_import(export_type, export_format_version())


def attachment_blob_member_path(attachment_id: int, mime_type: str) -> str:
    ext = mime_type_to_snapshot_extension(mime_type)
    return f"attachments/{attachment_id}.{ext}"


def snapshot_uses_json_envelopes(format_version: str) -> bool:
    """JSON table members are ``{format_version, table, rows}`` objects for ``format_version`` ≥ 2.0.0."""
    return _format_version_tuple(format_version) >= (2, 0, 0)


def detect_snapshot_container(data: bytes) -> SnapshotContainer:
    """Detect ZIP vs gzip-compressed tar from leading magic bytes."""
    if len(data) < 2:
        raise IncompleteSnapshotError(
            "snapshot file is empty or too small; expected a .zip or .tar.gz backup"
        )
    if data[:2] == b"\x1f\x8b":
        return "gzip"
    if data[:4] == b"PK\x03\x04" or data[:4] == b"PK\x05\x06" or data[:4] == b"PK\x07\x08":
        return "zip"
    raise IncompleteSnapshotError(
        "unrecognized snapshot container (expected ZIP .zip or gzip .tar.gz); "
        f"first bytes are {data[:4]!r}"
    )


def manifest_member_paths(
    export_type: str,
    format_version: str,
    payloads: dict[str, bytes],
) -> tuple[str, ...]:
    """FK-safe tar member order for ``format_version`` ≥ 2.0.0 (``member_manifest`` order)."""
    paths: list[str] = []
    attachment_blobs: list[str] = []
    for table in tables_for_import(export_type, format_version):
        if table == "attachments":
            paths.append("attachments.json")
            attachment_blobs = sorted(
                p for p in payloads if p.startswith("attachments/") and not p.endswith(".json")
            )
        elif table == "journal_entry_attachments":
            paths.append("journal_entry_attachments.json")
            paths.extend(attachment_blobs)
        else:
            paths.append(f"{table}.json")
    expected_keys = set(paths)
    if set(payloads.keys()) != expected_keys:
        raise IncompleteSnapshotError(
            f"internal export member set {sorted(payloads.keys())!r} "
            f"does not match manifest paths {sorted(expected_keys)!r}"
        )
    return tuple(paths)


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


def _canonical_envelope_bytes(table: str, rows: list[dict[str, Any]], format_version: str) -> bytes:
    return json.dumps(
        {
            "format_version": format_version,
            "table": table,
            "rows": rows,
        },
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


def _cell_to_jsonable(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column == "content_sha256" and isinstance(value, (bytes, memoryview)):
        raw = value if isinstance(value, bytes) else value.tobytes()
        return raw.hex()
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
        out.append({k: _cell_to_jsonable(k, v) for k, v in row.items()})
    return out


def _schema_versions_applied(conn: Connection) -> frozenset[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        versions = frozenset(str(r["version"]) for r in cur.fetchall())
    if not versions:
        raise RuntimeError("schema_migrations is empty")
    return versions


def current_schema_version(conn: Connection) -> str:
    return max(_schema_versions_applied(conn))


def _assert_snapshot_schema_compatible(conn: Connection, snap_schema: str) -> None:
    """Allow restore when the snapshot was taken at or before this DB revision.

    The snapshot records ``schema_version`` = ``MAX(schema_migrations.version)`` on the **source**.
    Import is allowed if that version is **recorded** on the target (a migration that was applied
    there) and the target is **not older** than the snapshot (target ``MAX`` ≥ snapshot value in
    lexicographic order, matching :func:`current_schema_version`).
    """
    applied = _schema_versions_applied(conn)
    db_max = max(applied)

    if snap_schema == db_max:
        return
    if snap_schema in applied and snap_schema < db_max:
        return
    if snap_schema > db_max:
        raise SchemaVersionMismatchError(
            f"snapshot has {snap_schema!r}, this database has {db_max!r} "
            "(snapshot is newer than this database; apply migrations or use an older release)"
        )
    raise SchemaVersionMismatchError(
        f"snapshot has {snap_schema!r}, this database has {db_max!r} "
        "(snapshot schema_version is not in this database's schema_migrations)"
    )


def _existing_ids(conn: Connection, table: str) -> set[int]:
    q = sql.SQL("SELECT id FROM {}").format(sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(q)
        return {int(r["id"]) for r in cur.fetchall()}


def _normalize_restore_mode(restore_mode: str) -> str:
    try:
        canonical = resolve_restore_mode(restore_mode)
    except ValueError as exc:
        raise IncompleteSnapshotError(str(exc)) from exc
    return canonical


def _reverse_tables_for_scope(tables: tuple[str, ...]) -> tuple[str, ...]:
    scope = set(tables)
    return tuple(t for t in reversed(COMPLETE_TABLES) if t in scope)


def _delete_incoming_ids_for_overwrite(
    conn: Connection,
    tables: tuple[str, ...],
    payloads: dict[str, list[dict[str, Any]]],
) -> None:
    """Remove existing rows whose primary key appears in the snapshot so INSERT can proceed."""
    for table in _reverse_tables_for_scope(tables):
        rows = payloads.get(table, [])
        if not rows:
            continue
        ids = sorted({int(r["id"]) for r in rows})
        try:
            del_stmt = sql.SQL("DELETE FROM {} WHERE id = ANY(%s)").format(sql.Identifier(table))
            with conn.cursor() as cur:
                cur.execute(del_stmt, (ids,))
        except pg_errors.ForeignKeyViolation as exc:
            raise SnapshotValidationError(
                f"overwrite could not delete existing row(s) in {table!r} "
                "(another table still references them). "
                "Try restore_mode erase-reload with a complete snapshot, or remove blocking rows. "
                f"Detail: {exc.diag.message_detail or exc}"
            ) from exc


def _truncate_complete_scope(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE TABLE
              cheque_register_filter_presets,
              journal_entry_filter_presets,
              import_templates,
              settlement_allocations,
              accrual_obligations,
              journal_lines,
              journal_entry_review_messages,
              journal_entry_attachments,
              attachments,
              journal_entries,
              import_batches,
              cheques,
              accrual_plans,
              party_match_patterns,
              parties,
              cel_rule_sets,
              ledger_settings,
              accounts
            RESTART IDENTITY CASCADE
            """
        )


def _fetch_table_rows(conn: Connection, table: str) -> list[dict[str, Any]]:
    q = sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(q)
        return [dict(r) for r in cur.fetchall()]


def _bytea_to_bytes(value: Any) -> bytes:
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytes):
        return value
    raise TypeError(f"expected BYTEA as bytes or memoryview, got {type(value).__name__}")


class _GzipTarChunkWriter(io.BufferedIOBase):
    """Writable sink; gzip/tar output is drained as chunks by :func:`_iter_pack_targz`."""

    def __init__(self) -> None:
        self._pending: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, b: bytes) -> int:
        if b:
            self._pending.append(bytes(b))
        return len(b)

    def flush(self) -> None:
        return None

    def drain(self) -> list[bytes]:
        out = self._pending
        self._pending = []
        return out


def _build_export_pack_inputs(
    conn: Connection,
    export_type: ExportType,
) -> tuple[tuple[str, ...], dict[str, bytes], bytes, int]:
    """Return ``member_paths``, member payloads, ``metadata.json`` bytes, and tar mtime."""
    fmt = export_format_version()
    tables = tables_for_export_type(export_type)
    schema_ver = current_schema_version(conn)
    export_local = datetime.now().astimezone()
    exported_at = export_local.astimezone(timezone.utc).isoformat()
    archive_mtime = int(export_local.timestamp())

    payloads: dict[str, bytes] = {}
    for table in tables:
        rows = _fetch_table_rows(conn, table)
        if table == "attachments":
            raw_out: list[dict[str, Any]] = []
            for row in rows:
                rid = int(row["id"])
                blob = _bytea_to_bytes(row["blob"])
                mime = str(row["mime_type"])
                member_path = attachment_blob_member_path(rid, mime)
                payloads[member_path] = blob
                raw_out.append(
                    {k: _cell_to_jsonable(k, v) for k, v in row.items() if k != "blob"},
                )
            payloads["attachments.json"] = _canonical_envelope_bytes("attachments", raw_out, fmt)
        else:
            raw = _rows_jsonable(rows)
            payloads[f"{table}.json"] = _canonical_envelope_bytes(table, raw, fmt)

    member_paths = manifest_member_paths(export_type, fmt, payloads)
    manifest: list[dict[str, str]] = [
        {"path": path, "sha256": _sha256_hex(payloads[path])} for path in member_paths
    ]

    metadata_obj: dict[str, Any] = {
        "export_type": export_type,
        "format_version": fmt,
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
    return member_paths, payloads, metadata_bytes, archive_mtime


def _iter_pack_targz(
    member_paths: tuple[str, ...],
    payloads: dict[str, bytes],
    metadata_bytes: bytes,
    *,
    mtime: int | None = None,
) -> Iterator[bytes]:
    """Write data members in ``member_paths`` order, then ``metadata.json`` (gzip level 9)."""
    member_mtime = int(datetime.now().astimezone().timestamp()) if mtime is None else mtime
    writer = _GzipTarChunkWriter()
    with gzip.GzipFile(fileobj=writer, mode="wb", compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for path in member_paths:
                data = payloads[path]
                info = tarfile.TarInfo(name=path)
                info.size = len(data)
                info.mtime = member_mtime
                tar.addfile(info, io.BytesIO(data))
            meta_info = tarfile.TarInfo(name="metadata.json")
            meta_info.size = len(metadata_bytes)
            meta_info.mtime = member_mtime
            tar.addfile(meta_info, io.BytesIO(metadata_bytes))
        for part in writer.drain():
            yield part
    for part in writer.drain():
        yield part


def _pack_targz(
    member_paths: tuple[str, ...],
    payloads: dict[str, bytes],
    metadata_bytes: bytes,
    *,
    mtime: int | None = None,
) -> bytes:
    return b"".join(_iter_pack_targz(member_paths, payloads, metadata_bytes, mtime=mtime))


def iter_export_snapshot(conn: Connection, export_type: ExportType) -> Iterator[bytes]:
    """Yield gzip-compressed tar snapshot chunks (``format_version`` 2.0.0)."""
    member_paths, payloads, metadata_bytes, archive_mtime = _build_export_pack_inputs(
        conn,
        export_type,
    )
    yield from _iter_pack_targz(
        member_paths,
        payloads,
        metadata_bytes,
        mtime=archive_mtime,
    )


def export_snapshot(conn: Connection, export_type: ExportType) -> bytes:
    """Build a gzip-compressed tar snapshot (``format_version`` 2.0.0)."""
    return b"".join(iter_export_snapshot(conn, export_type))


def export_complete_snapshot(conn: Connection) -> bytes:
    """Build a complete snapshot archive (backward-compatible name)."""
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
                raise SnapshotIntegrityError(
                    f"SHA-256 checksum mismatch for ZIP member {path!r} "
                    "(file may be corrupted or tampered with)"
                )

        expected = manifest_paths | {"metadata.json"}
        if names != expected:
            extra = names - expected
            missing = expected - names
            msg_parts = []
            if extra:
                msg_parts.append(f"unexpected ZIP members: {sorted(extra)}")
            if missing:
                msg_parts.append(f"missing ZIP members: {sorted(missing)}")
            raise SnapshotIntegrityError(
                "; ".join(msg_parts)
                + " — ZIP entries must match metadata.json member_manifest exactly (extra files are rejected)"
            )

        files = {n: zf.read(n) for n in names if n != "metadata.json"}
    return metadata, files


def _read_targz_member_bodies(readable: BinaryIO) -> tuple[list[str], dict[str, bytes]]:
    """Read all file members from a gzip-wrapped tar stream."""
    members_ordered: list[str] = []
    files: dict[str, bytes] = {}
    with gzip.GzipFile(fileobj=readable, mode="rb") as gz:
        with tarfile.open(fileobj=gz, mode="r:") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise IncompleteSnapshotError(f"could not read tar member {member.name!r}")
                body = extracted.read()
                members_ordered.append(member.name)
                files[member.name] = body
    return members_ordered, files


def _validate_targz_member_bodies(
    members_ordered: list[str],
    files: dict[str, bytes],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not members_ordered:
        raise IncompleteSnapshotError("tar.gz snapshot contains no members")
    if members_ordered[-1] != "metadata.json":
        raise IncompleteSnapshotError(
            "metadata.json must be the last member in a tar.gz snapshot "
            f"(found order ending with {members_ordered[-3:]!r})"
        )

    metadata = _parse_metadata(files["metadata.json"])
    manifest = metadata.get("member_manifest")
    if not isinstance(manifest, list):
        raise IncompleteSnapshotError("metadata.member_manifest must be a list")

    manifest_paths: list[str] = []
    for item in manifest:
        if not isinstance(item, dict):
            raise IncompleteSnapshotError("member_manifest entries must be objects")
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise IncompleteSnapshotError("member_manifest items need path and sha256 strings")
        manifest_paths.append(path)
        if path not in files:
            raise IncompleteSnapshotError(f"tar.gz is missing member {path!r} listed in manifest")
        body = files[path]
        if _sha256_hex(body) != digest.lower():
            raise SnapshotIntegrityError(
                f"SHA-256 checksum mismatch for tar member {path!r} "
                "(file may be corrupted or tampered with)"
            )

    names = set(files.keys())
    expected = set(manifest_paths) | {"metadata.json"}
    if names != expected:
        extra = names - expected
        missing = expected - names
        msg_parts = []
        if extra:
            msg_parts.append(f"unexpected tar members: {sorted(extra)}")
        if missing:
            msg_parts.append(f"missing tar members: {sorted(missing)}")
        raise SnapshotIntegrityError(
            "; ".join(msg_parts)
            + " — tar entries must match metadata.json member_manifest exactly "
            "(metadata.json is last and not listed in the manifest)"
        )

    data_order = members_ordered[:-1]
    if data_order != manifest_paths:
        raise SnapshotIntegrityError(
            "tar member order does not match metadata.member_manifest order "
            f"(tar has {data_order!r}, manifest has {manifest_paths!r})"
        )

    return metadata, {n: files[n] for n in names if n != "metadata.json"}


def _load_targz_members(targz_bytes: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    try:
        members_ordered, files = _read_targz_member_bodies(io.BytesIO(targz_bytes))
    except (gzip.BadGzipFile, OSError, tarfile.TarError) as exc:
        raise IncompleteSnapshotError("not a valid gzip-compressed tar archive") from exc
    return _validate_targz_member_bodies(members_ordered, files)


def load_targz_members_from_stream(readable: BinaryIO) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Load and validate a tar.gz snapshot from a readable byte stream (#252)."""
    try:
        members_ordered, files = _read_targz_member_bodies(readable)
    except (gzip.BadGzipFile, OSError, tarfile.TarError) as exc:
        raise IncompleteSnapshotError("not a valid gzip-compressed tar archive") from exc
    return _validate_targz_member_bodies(members_ordered, files)


def _load_archive_members(archive_bytes: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    container = detect_snapshot_container(archive_bytes)
    if container == "zip":
        return _load_zip_members(archive_bytes)
    return _load_targz_members(archive_bytes)


def _parse_table_file(path: str, raw: bytes, *, format_version: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IncompleteSnapshotError(f"{path} is not valid UTF-8 JSON") from exc

    if snapshot_uses_json_envelopes(format_version):
        if not isinstance(data, dict):
            raise IncompleteSnapshotError(f"{path} must be a JSON envelope object for format 2.0.0")
        table = data.get("table")
        rows = data.get("rows")
        env_fmt = data.get("format_version")
        if not isinstance(table, str):
            raise IncompleteSnapshotError(f"{path} envelope must include string table")
        if not isinstance(env_fmt, str):
            raise IncompleteSnapshotError(f"{path} envelope must include string format_version")
        expected_table = path.removesuffix(".json")
        if table != expected_table:
            raise IncompleteSnapshotError(
                f"{path} envelope table={table!r} does not match member name "
                f"(expected {expected_table!r})"
            )
        if env_fmt != format_version:
            raise IncompleteSnapshotError(
                f"{path} envelope format_version={env_fmt!r} "
                f"does not match metadata format_version={format_version!r}"
            )
        if not isinstance(rows, list):
            raise IncompleteSnapshotError(f"{path} envelope rows must be a JSON array")
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise IncompleteSnapshotError(f"{path} row {i} must be a JSON object")
        return rows

    if not isinstance(data, list):
        raise IncompleteSnapshotError(f"{path} must be a JSON array of row objects")
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise IncompleteSnapshotError(f"{path} row {i} must be a JSON object")
    return data


def _coerce_cell(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column == "content_sha256":
        if isinstance(value, str):
            return bytes.fromhex(value)
        raise SnapshotValidationError("content_sha256 must be a 64-character hex string")
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
    if column in ("day_of_week", "day_of_month", "month_of_year", "sort_order", "cheque_number"):
        return int(value) if value is not None else None
    return value


def _prepare_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    out = {k: _coerce_cell(k, v) for k, v in row.items()}
    if table == "accrual_plans":
        out.pop("bridge_account_id", None)
    return out


def _validate_journal(lines: list[dict[str, Any]]) -> None:
    by_entry: dict[int, Decimal] = {}
    for line in lines:
        eid = int(line["entry_id"])
        amt = Decimal(str(line["amount"]))
        by_entry[eid] = by_entry.get(eid, Decimal("0")) + amt
    bad = {eid: total for eid, total in by_entry.items() if total != 0}
    if bad:
        raise SnapshotValidationError(
            "journal lines do not balance (per entry_id, line amounts must sum to zero); "
            "offending entry_id(s): "
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


def _validate_filter_preset_definitions_against_config(
    presets: list[dict[str, Any]],
    *,
    accounts: set[int],
    parties: set[int],
    accrual_plans: set[int],
) -> None:
    """Embedded ids in a preset ``definition`` must match the archive's configuration set."""
    from tallybadger.ledger.date_range_math import (
        DateRangeMathError,
        parse_optional_entry_date_expression,
        resolve_entry_date_range,
    )

    for i, row in enumerate(presets):
        defn = row.get("definition")
        if not isinstance(defn, dict):
            raise SnapshotValidationError(
                f"journal_entry_filter_presets[{i}] definition must be a JSON object"
            )
        for field_name, allowed in (
            ("account_ids", accounts),
            ("party_ids", parties),
            ("accrual_plan_ids", accrual_plans),
        ):
            for v in defn.get(field_name, []) or []:
                if int(v) not in allowed:
                    raise SnapshotValidationError(
                        f"journal_entry_filter_presets[{i}] definition.{field_name} "
                        f"contains id={v} that has no matching row in the archive"
                    )
        raw_from = defn.get("from_date")
        raw_to = defn.get("to_date")
        if raw_from is not None or raw_to is not None:
            try:
                if raw_from is not None:
                    expr_from = (
                        raw_from.isoformat()
                        if hasattr(raw_from, "isoformat")
                        else str(raw_from).strip()
                    )
                    if not expr_from:
                        raise DateRangeMathError("from_date must not be empty")
                    parse_optional_entry_date_expression(expr_from)
                if raw_to is not None:
                    expr_to = (
                        raw_to.isoformat()
                        if hasattr(raw_to, "isoformat")
                        else str(raw_to).strip()
                    )
                    if not expr_to:
                        raise DateRangeMathError("to_date must not be empty")
                    parse_optional_entry_date_expression(expr_to)
                if raw_from is not None and raw_to is not None:
                    expr_from = (
                        raw_from.isoformat()
                        if hasattr(raw_from, "isoformat")
                        else str(raw_from).strip()
                    )
                    expr_to = (
                        raw_to.isoformat()
                        if hasattr(raw_to, "isoformat")
                        else str(raw_to).strip()
                    )
                    resolve_entry_date_range(expr_from, expr_to)
            except DateRangeMathError as exc:
                raise SnapshotValidationError(
                    f"journal_entry_filter_presets[{i}] definition date range: {exc}",
                ) from exc


def _validate_configuration_fks(
    payloads: dict[str, list[dict[str, Any]]],
    *,
    conn: Connection | None = None,
) -> None:
    acct = {int(r["id"]) for r in payloads["accounts"]}
    party = {int(r["id"]) for r in payloads["parties"]}
    cel = {int(r["id"]) for r in payloads["cel_rule_sets"]}

    if "accrual_plans" in payloads:
        plans = {int(r["id"]) for r in payloads["accrual_plans"]}
    elif conn is not None:
        plans = _existing_ids(conn, "accrual_plans")
    else:
        plans = set()

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

    for i, row in enumerate(payloads.get("accrual_plans", [])):
        if int(row["party_id"]) not in party:
            raise SnapshotValidationError(
                f"accrual_plans[{i}] party_id={row['party_id']} has no matching row in parties.json"
            )
        if int(row["target_account_id"]) not in acct:
            raise SnapshotValidationError(
                f"accrual_plans[{i}] target_account_id={row['target_account_id']} "
                "has no matching row in accounts.json"
            )

    account_cols = (
        "accounts_receivable_account_id",
        "accounts_payable_account_id",
        "unearned_revenue_account_id",
        "prepaid_expenses_account_id",
        "unallocated_debits_account_id",
        "unallocated_credits_account_id",
        "default_cheque_credit_account_id",
        "default_cheque_debit_account_id",
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

    presets = payloads.get(JOURNAL_ENTRY_FILTER_PRESET_TABLE)
    if presets is not None:
        _validate_filter_preset_definitions_against_config(
            presets,
            accounts=acct,
            parties=party,
            accrual_plans=plans,
        )

    cheque_presets = payloads.get(CHEQUE_REGISTER_FILTER_PRESET_TABLE)
    if cheque_presets is not None:
        _validate_cheque_register_filter_preset_definitions_against_config(
            cheque_presets,
            accounts=acct,
            parties=party,
        )


def _validate_cheque_register_filter_preset_definitions_against_config(
    presets: list[dict[str, Any]],
    *,
    accounts: set[int],
    parties: set[int],
) -> None:
    """Embedded ids in cheque preset ``definition`` must match configuration members."""
    for i, row in enumerate(presets):
        defn = row.get("definition")
        if not isinstance(defn, dict):
            raise SnapshotValidationError(
                f"cheque_register_filter_presets[{i}] definition must be a JSON object"
            )
        for v in defn.get("party_ids", []) or []:
            if v == "null":
                continue
            if int(v) not in parties:
                raise SnapshotValidationError(
                    f"cheque_register_filter_presets[{i}] definition.party_ids "
                    f"contains id={v} that has no matching row in the archive"
                )
        for field_name in ("credit_account_ids", "debit_account_ids"):
            for v in defn.get(field_name, []) or []:
                if int(v) not in accounts:
                    raise SnapshotValidationError(
                        f"cheque_register_filter_presets[{i}] definition.{field_name} "
                        f"contains id={v} that has no matching row in the archive"
                    )


def _normalize_legacy_settlement_payloads(
    payloads: dict[str, list[dict[str, Any]]],
    format_version: str,
) -> None:
    """Convert pre-1.6.0 settlement_events + allocations into allocations-only rows."""
    if not snapshot_includes_settlement_events(format_version):
        return
    events = {int(r["id"]): r for r in payloads.get("settlement_events", [])}
    normalized: list[dict[str, Any]] = []
    for row in payloads.get("settlement_allocations", []):
        ev = events.get(int(row["settlement_event_id"]))
        if ev is None:
            raise SnapshotValidationError(
                f"settlement_allocations id={row.get('id')} references missing settlement_event_id"
            )
        nr = {k: v for k, v in row.items() if k != "settlement_event_id"}
        nr["entry_id"] = int(ev["entry_id"])
        normalized.append(nr)
    payloads["settlement_allocations"] = normalized
    payloads.pop("settlement_events", None)


def _validate_settlement_allocations_fks(
    payloads: dict[str, list[dict[str, Any]]],
    *,
    je: set[int],
    ao: set[int],
    format_version: str,
    archive_label: str = "journal_entries.json",
    obligation_label: str = "accrual_obligations.json",
) -> None:
    legacy = snapshot_includes_settlement_events(format_version)
    se: set[int] = set()
    if legacy:
        se = {int(r["id"]) for r in payloads.get("settlement_events", [])}

    for i, row in enumerate(payloads.get("settlement_allocations", [])):
        if legacy:
            if int(row["settlement_event_id"]) not in se:
                raise SnapshotValidationError(
                    f"settlement_allocations[{i}] settlement_event_id={row['settlement_event_id']} "
                    "has no matching row in settlement_events.json"
                )
        else:
            if int(row["entry_id"]) not in je:
                raise SnapshotValidationError(
                    f"settlement_allocations[{i}] entry_id={row['entry_id']} "
                    f"has no matching row in {archive_label}"
                )
        if int(row["obligation_id"]) not in ao:
            raise SnapshotValidationError(
                f"settlement_allocations[{i}] obligation_id={row['obligation_id']} "
                f"has no matching row in {obligation_label}"
            )


def _validate_legacy_settlement_events_fks(
    payloads: dict[str, list[dict[str, Any]]],
    *,
    acct: set[int],
    party: set[int],
    je: set[int],
    party_scope_label: str = "parties.json",
    account_scope_label: str = "accounts.json",
) -> None:
    for i, row in enumerate(payloads.get("settlement_events", [])):
        if int(row["party_id"]) not in party:
            raise SnapshotValidationError(
                f"settlement_events[{i}] party_id={row['party_id']} "
                f"has no matching row in {party_scope_label}"
            )
        if int(row["cash_account_id"]) not in acct:
            raise SnapshotValidationError(
                f"settlement_events[{i}] cash_account_id={row['cash_account_id']} "
                f"has no matching row in {account_scope_label}"
            )
        if int(row["entry_id"]) not in je:
            raise SnapshotValidationError(
                f"settlement_events[{i}] entry_id={row['entry_id']} "
                "has no matching row in journal_entries.json"
            )


def _validate_complete_fk_graph(
    payloads: dict[str, list[dict[str, Any]]],
    format_version: str,
) -> None:
    """All FK targets appear in this archive (complete export)."""
    _validate_configuration_fks(payloads)

    acct = {int(r["id"]) for r in payloads["accounts"]}
    party = {int(r["id"]) for r in payloads["parties"]}
    plans = {int(r["id"]) for r in payloads["accrual_plans"]}
    je = {int(r["id"]) for r in payloads["journal_entries"]}
    jl = {int(r["id"]) for r in payloads["journal_lines"]}
    ao = {int(r["id"]) for r in payloads["accrual_obligations"]}

    batch_ids: set[int] | None = None
    if "import_batches" in payloads:
        batch_ids = {int(r["id"]) for r in payloads["import_batches"]}

    chq: set[int] = set()
    if "cheques" in payloads:
        chq = {int(r["id"]) for r in payloads["cheques"]}
        for i, row in enumerate(payloads["cheques"]):
            if int(row["credit_account_id"]) not in acct:
                raise SnapshotValidationError(
                    f"cheques[{i}] credit_account_id={row['credit_account_id']} "
                    "has no matching row in accounts.json"
                )
            if int(row["debit_account_id"]) not in acct:
                raise SnapshotValidationError(
                    f"cheques[{i}] debit_account_id={row['debit_account_id']} "
                    "has no matching row in accounts.json"
                )
            pid = row.get("party_id")
            if pid is not None and int(pid) not in party:
                raise SnapshotValidationError(
                    f"cheques[{i}] party_id={pid} has no matching row in parties.json"
                )

    for i, row in enumerate(payloads["journal_entries"]):
        ap = row.get("accrual_plan_id")
        if ap is not None and int(ap) not in plans:
            raise SnapshotValidationError(
                f"journal_entries[{i}] accrual_plan_id={ap} has no matching row in accrual_plans.json"
            )
        cid = row.get("cheque_id")
        if cid is not None and int(cid) not in chq:
            raise SnapshotValidationError(
                f"journal_entries[{i}] cheque_id={cid} has no matching row in cheques.json"
            )
        ib = row.get("import_batch_id")
        if ib is not None and batch_ids is not None and int(ib) not in batch_ids:
            raise SnapshotValidationError(
                f"journal_entries[{i}] import_batch_id={ib} has no matching row in import_batches.json"
            )

    if "journal_entry_review_messages" in payloads:
        for i, row in enumerate(payloads["journal_entry_review_messages"]):
            eid = int(row["journal_entry_id"])
            if eid not in je:
                raise SnapshotValidationError(
                    f"journal_entry_review_messages[{i}] journal_entry_id={eid} "
                    "has no matching row in journal_entries.json"
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

    if snapshot_includes_settlement_events(format_version):
        _validate_legacy_settlement_events_fks(
            payloads,
            acct=acct,
            party=party,
            je=je,
        )

    _validate_settlement_allocations_fks(
        payloads,
        je=je,
        ao=ao,
        format_version=format_version,
    )

    if "journal_entry_attachments" in payloads:
        att_ids = {int(r["id"]) for r in payloads["attachments"]}
        for i, row in enumerate(payloads["journal_entry_attachments"]):
            eid = int(row["journal_entry_id"])
            if eid not in je:
                raise SnapshotValidationError(
                    f"journal_entry_attachments[{i}] journal_entry_id={eid} "
                    "has no matching row in journal_entries.json"
                )
            aid = int(row["attachment_id"])
            if aid not in att_ids:
                raise SnapshotValidationError(
                    f"journal_entry_attachments[{i}] attachment_id={aid} "
                    "has no matching row in attachments.json"
                )


def _validate_financial_fks(
    conn: Connection,
    payloads: dict[str, list[dict[str, Any]]],
    format_version: str,
) -> None:
    """Financial rows reference configuration entities that must already exist in the target DB."""
    acct_db = _existing_ids(conn, "accounts")
    party_db = _existing_ids(conn, "parties")

    plan_snap: set[int] = set()
    if "accrual_plans" in payloads:
        plan_snap = {int(r["id"]) for r in payloads["accrual_plans"]}
        for i, row in enumerate(payloads["accrual_plans"]):
            if int(row["party_id"]) not in party_db:
                raise SnapshotValidationError(
                    f"accrual_plans[{i}] party_id={row['party_id']} not found in target database."
                )
            if int(row["target_account_id"]) not in acct_db:
                raise SnapshotValidationError(
                    f"accrual_plans[{i}] target_account_id={row['target_account_id']} "
                    "not found in target database."
                )
    plan_db = plan_snap | _existing_ids(conn, "accrual_plans")

    chq: set[int] = set()
    if "cheques" in payloads:
        chq = {int(r["id"]) for r in payloads["cheques"]}
        for i, row in enumerate(payloads["cheques"]):
            if int(row["credit_account_id"]) not in acct_db:
                raise SnapshotValidationError(
                    f"cheques[{i}] credit_account_id={row['credit_account_id']} not found in target database."
                )
            if int(row["debit_account_id"]) not in acct_db:
                raise SnapshotValidationError(
                    f"cheques[{i}] debit_account_id={row['debit_account_id']} not found in target database."
                )
            pid = row.get("party_id")
            if pid is not None and int(pid) not in party_db:
                raise SnapshotValidationError(
                    f"cheques[{i}] party_id={pid} not found in target database."
                )

    je = {int(r["id"]) for r in payloads["journal_entries"]}
    jl = {int(r["id"]) for r in payloads["journal_lines"]}
    ao = {int(r["id"]) for r in payloads["accrual_obligations"]}

    batch_snap: set[int] = set()
    if "import_batches" in payloads:
        batch_snap = {int(r["id"]) for r in payloads["import_batches"]}
    batch_db = _existing_ids(conn, "import_batches")

    for i, row in enumerate(payloads["journal_entries"]):
        ap = row.get("accrual_plan_id")
        if ap is not None and int(ap) not in plan_db:
            if plan_snap and int(ap) not in plan_snap:
                raise SnapshotValidationError(
                    f"journal_entries[{i}] accrual_plan_id={ap} not found in accrual_plans.json "
                    "or in the target database (import configuration first, or include the plan "
                    "in the financial snapshot)."
                )
            raise SnapshotValidationError(
                f"journal_entries[{i}] accrual_plan_id={ap} not found in target database "
                "(financial snapshots do not include accrual_plans; import configuration first "
                "or fix the snapshot)."
            )
        cid = row.get("cheque_id")
        if cid is not None and int(cid) not in chq:
            raise SnapshotValidationError(
                f"journal_entries[{i}] cheque_id={cid} has no matching row in cheques.json"
            )
        ib = row.get("import_batch_id")
        if ib is not None:
            bid = int(ib)
            if bid not in batch_snap and bid not in batch_db:
                raise SnapshotValidationError(
                    f"journal_entries[{i}] import_batch_id={ib} not found in import_batches.json "
                    "or in the target database (import configuration first, or include the batch "
                    "in the financial snapshot)."
                )

    if "journal_entry_review_messages" in payloads:
        for i, row in enumerate(payloads["journal_entry_review_messages"]):
            eid = int(row["journal_entry_id"])
            if eid not in je:
                raise SnapshotValidationError(
                    f"journal_entry_review_messages[{i}] journal_entry_id={eid} "
                    "has no matching row in journal_entries.json"
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
            if plan_snap and int(ap) not in plan_snap:
                raise SnapshotValidationError(
                    f"accrual_obligations[{i}] accrual_plan_id={ap} not found in accrual_plans.json "
                    "or in the target database."
                )
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

    if snapshot_includes_settlement_events(format_version):
        _validate_legacy_settlement_events_fks(
            payloads,
            acct=acct_db,
            party=party_db,
            je=je,
            party_scope_label="target database",
            account_scope_label="target database",
        )

    _validate_settlement_allocations_fks(
        payloads,
        je=je,
        ao=ao,
        format_version=format_version,
        archive_label="journal_entries.json",
        obligation_label="accrual_obligations.json",
    )

    if "journal_entry_attachments" in payloads:
        att_ids = {int(r["id"]) for r in payloads["attachments"]}
        for i, row in enumerate(payloads["journal_entry_attachments"]):
            eid = int(row["journal_entry_id"])
            if eid not in je:
                raise SnapshotValidationError(
                    f"journal_entry_attachments[{i}] journal_entry_id={eid} "
                    "has no matching row in journal_entries.json"
                )
            aid = int(row["attachment_id"])
            if aid not in att_ids:
                raise SnapshotValidationError(
                    f"journal_entry_attachments[{i}] attachment_id={aid} "
                    "has no matching row in attachments.json"
                )


def _expected_manifest_paths(
    export_type: str,
    format_version: str,
    files: dict[str, bytes],
) -> set[str]:
    tables = tables_for_import(export_type, format_version)
    expected: set[str] = {f"{t}.json" for t in tables}
    if snapshot_includes_attachment_tables(format_version) and export_type in (
        "complete",
        "financial",
    ):
        path = "attachments.json"
        if path not in files:
            raise IncompleteSnapshotError(f"missing {path}")
        for row in _parse_table_file(path, files[path], format_version=format_version):
            expected.add(
                attachment_blob_member_path(int(row["id"]), str(row["mime_type"])),
            )
    return expected


def _assert_manifest_matches_export_type(
    metadata: dict[str, Any],
    files: dict[str, bytes],
    export_type: str,
    format_version: str,
) -> None:
    manifest = metadata.get("member_manifest")
    if not isinstance(manifest, list):
        return
    paths = {item["path"] for item in manifest if isinstance(item, dict) and "path" in item}
    expected = _expected_manifest_paths(export_type, format_version, files)
    if paths != expected:
        raise IncompleteSnapshotError(
            f"archive member set {sorted(paths)!r} does not match export_type {export_type!r} "
            f"and format_version {format_version!r} (expected {sorted(expected)!r})"
        )


def _apply_snapshot_import(
    conn: Connection,
    metadata: dict[str, Any],
    files: dict[str, bytes],
    *,
    restore_mode: str,
) -> str | None:
    """Insert snapshot rows after archive members are loaded and validated."""
    mode = _normalize_restore_mode(restore_mode)

    export_type_raw: Any = metadata.get("export_type")
    if not isinstance(export_type_raw, str):
        raise IncompleteSnapshotError("metadata.export_type must be a string")
    export_type = export_type_raw
    if export_type not in SUPPORTED_EXPORT_TYPES:
        raise IncompleteSnapshotError(
            f"unsupported export_type {export_type!r}; expected one of {sorted(SUPPORTED_EXPORT_TYPES)}"
        )

    fmt: Any = metadata.get("format_version")
    if not isinstance(fmt, str):
        raise IncompleteSnapshotError("metadata.format_version must be a string")
    if fmt not in supported_import_format_versions():
        raise UnsupportedFormatVersionError(
            "archive has "
            f"{fmt!r}; this release imports {sorted(supported_import_format_versions())} "
            f"(current and up to three prior format versions; see STYLE.md)"
        )

    _assert_manifest_matches_export_type(metadata, files, export_type, fmt)
    tables = tables_for_import(export_type, fmt)

    if mode == "erase-reload" and export_type == "financial":
        raise SnapshotValidationError(
            "restore_mode erase-reload cannot import a financial-only snapshot: "
            "the database is cleared first, so accounts/parties/plans would be missing. "
            "Use a complete or configuration snapshot for erase-reload, "
            "or import configuration then financial with abort/overwrite."
        )

    snap_schema: Any = metadata.get("schema_version")
    if not isinstance(snap_schema, str):
        raise IncompleteSnapshotError("metadata.schema_version must be a string")

    _assert_snapshot_schema_compatible(conn, snap_schema)

    payloads: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        path = f"{table}.json"
        if path not in files:
            raise IncompleteSnapshotError(f"missing {path}")
        payloads[table] = _parse_table_file(path, files[path], format_version=fmt)

    _validate_payloads_for_tables(tables, payloads)

    if export_type == "complete":
        _validate_complete_fk_graph(payloads, fmt)
    elif export_type == "configuration":
        _validate_configuration_fks(payloads, conn=conn)
    else:
        _validate_financial_fks(conn, payloads, fmt)

    _normalize_legacy_settlement_payloads(payloads, fmt)
    insert_tables = tuple(t for t in tables if t != "settlement_events")

    with conn.transaction():
        # Foreign keys on snapshot tables are DEFERRABLE INITIALLY IMMEDIATE (migration 015).
        # Defer to COMMIT so bulk INSERT/DELETE can reorder without intermediate FK failures.
        # PK/UNIQUE/CHECK stay immediate (PostgreSQL cannot ALTER those to deferrable here).
        with conn.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")

        if mode == "erase-reload":
            _truncate_complete_scope(conn)
        elif mode == "overwrite":
            _delete_incoming_ids_for_overwrite(conn, insert_tables, payloads)

        for table in insert_tables:
            rows = [_prepare_row(table, r) for r in payloads[table]]
            if table == "attachments":
                for row in rows:
                    aid = int(row["id"])
                    blob_path = attachment_blob_member_path(aid, str(row["mime_type"]))
                    row["blob"] = files.get(blob_path, b"")
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

    return format_deprecation_warning(fmt)


def import_snapshot(
    conn: Connection,
    archive_bytes: bytes,
    *,
    restore_mode: str = "abort",
) -> str | None:
    """Import a snapshot; tables loaded match ``export_type`` in metadata.

    ``restore_mode`` applies only to this import and is never read from the archive:
    ``abort`` — insert in one transaction; first PK/unique/FK/business-rule failure rolls back.
    ``overwrite`` — before insert, delete existing rows with the same primary keys as the
    snapshot (in FK-safe reverse order within the snapshot's table set).
    ``erase-reload`` — truncate all snapshot data tables, then load (requires a
    self-contained archive: not ``financial``-only).

    Returns an optional format-deprecation warning for supported archives older than the
    current export version (#202); ``None`` when the archive uses the current format.
    """
    metadata, files = _load_archive_members(archive_bytes)
    return _apply_snapshot_import(conn, metadata, files, restore_mode=restore_mode)


def import_snapshot_from_gzip_stream(
    conn: Connection,
    readable: BinaryIO,
    *,
    restore_mode: str = "abort",
) -> str | None:
    """Import a tar.gz snapshot from a byte stream without buffering the whole archive (#252)."""
    metadata, files = load_targz_members_from_stream(readable)
    return _apply_snapshot_import(conn, metadata, files, restore_mode=restore_mode)


def import_complete_snapshot(
    conn: Connection,
    archive_bytes: bytes,
    *,
    restore_mode: str = "abort",
) -> str | None:
    """Import a snapshot (backward-compatible name; any ``export_type`` in the archive)."""
    return import_snapshot(conn, archive_bytes, restore_mode=restore_mode)


def _resync_serials(conn: Connection) -> None:
    for table in (
        "accounts",
        "parties",
        "party_match_patterns",
        "accrual_plans",
        "cel_rule_sets",
        "cheques",
        "import_batches",
        "journal_entries",
        "journal_entry_review_messages",
        "journal_lines",
        "accrual_obligations",
        "settlement_allocations",
        "attachments",
        "journal_entry_attachments",
        "import_templates",
        "journal_entry_filter_presets",
        "cheque_register_filter_presets",
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
