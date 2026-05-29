"""Round-trip tests for complete JSON ZIP snapshots (#67)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import hashlib
import io
import json
import os
import zipfile

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

import tallybadger.core.config as core_config
from tallybadger.main import app

from psycopg import errors as pg_errors

from tallybadger.backup.errors import (
    IncompleteSnapshotError,
    SchemaVersionMismatchError,
    SnapshotIntegrityError,
    SnapshotValidationError,
    UnsupportedFormatVersionError,
)
from tallybadger.backup.snapshot import (
    COMPLETE_TABLES,
    CONFIGURATION_TABLES,
    attachment_blob_member_path,
    current_schema_version,
    export_complete_snapshot,
    export_format_version,
    export_snapshot,
    financial_tables_for_format,
    format_deprecation_warning,
    import_complete_snapshot,
    import_snapshot,
    oldest_supported_import_format_version,
    snapshot_includes_attachment_tables,
    snapshot_table_counts,
    tables_for_import,
)
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import (
    AccrualPlanCreate,
    AccountCreate,
    JournalEntryWrite,
    JournalLineIn,
    PartyCreate,
)
from tallybadger.ledger.service import LedgerService

pytestmark = pytest.mark.integration


def _truncate_all_data(integration_db_url: str) -> None:
    with connect(integration_db_url) as conn:
        with conn.transaction():
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


def _ensure_ledger_settings(integration_db_url: str) -> None:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("INSERT INTO ledger_settings (id) VALUES (1)")


@pytest.fixture(scope="session")
def integration_db_url() -> str:
    db_url = os.environ.get("TALLYBADGER_TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TALLYBADGER_TEST_DATABASE_URL not set; skipping integration tests")
    return db_url


@pytest.fixture(scope="session", autouse=True)
def migrated_database(integration_db_url: str) -> None:
    apply_sql_migrations(integration_db_url)


@pytest.fixture(autouse=True)
def clean_backup_database(integration_db_url: str) -> Iterator[None]:
    _truncate_all_data(integration_db_url)
    _ensure_ledger_settings(integration_db_url)
    yield
    _truncate_all_data(integration_db_url)


@pytest.fixture
def ledger_service(integration_db_url: str) -> LedgerService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return LedgerService(connection_factory=connection_factory)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rezip_table_members_with_metadata(table_members: dict[str, bytes], metadata: dict) -> bytes:
    """Rebuild metadata.manifest hashes from table JSON bytes and write a new ZIP."""
    manifest = [{"path": p, "sha256": _sha256(table_members[p])} for p in sorted(table_members)]
    meta_out = {**metadata, "member_manifest": manifest}
    meta_bytes = json.dumps(
        meta_out,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", meta_bytes)
        for path in sorted(table_members):
            zf.writestr(path, table_members[path])
    return buf.getvalue()


def _replace_metadata_only(zip_bytes: bytes, **meta_patch: object) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(zip_bytes))
    try:
        meta = json.loads(zin.read("metadata.json").decode("utf-8"))
        meta.update(meta_patch)
        new_meta = json.dumps(
            meta,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name in zin.namelist():
                if name.endswith("/"):
                    continue
                if name == "metadata.json":
                    zout.writestr(name, new_meta)
                else:
                    zout.writestr(name, zin.read(name))
    finally:
        zin.close()
    return out.getvalue()


def _repack_snapshot_for_format(
    zip_bytes: bytes,
    format_version: str,
    *,
    export_type: str = "complete",
) -> bytes:
    """Rebuild a current-schema export ZIP for an older ``format_version`` member matrix."""
    zin = zipfile.ZipFile(io.BytesIO(zip_bytes))
    try:
        meta = json.loads(zin.read("metadata.json").decode("utf-8"))
        table_members: dict[str, bytes] = {}
        for name in zin.namelist():
            if name.endswith("/") or name == "metadata.json":
                continue
            table_members[name] = zin.read(name)

        required_tables = tables_for_import(export_type, format_version)
        cleaned: dict[str, bytes] = {}
        for table in required_tables:
            path = f"{table}.json"
            cleaned[path] = table_members.get(path, b"[]")

        if snapshot_includes_attachment_tables(format_version):
            for path, data in table_members.items():
                if path.startswith("attachments/"):
                    cleaned[path] = data

        meta_out = {
            k: v
            for k, v in meta.items()
            if k not in ("member_manifest", "format_version", "export_type")
        }
        meta_out["format_version"] = format_version
        meta_out["export_type"] = export_type
        return _rezip_table_members_with_metadata(cleaned, meta_out)
    finally:
        zin.close()


def _seed_minimal_ledger(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ledger_service.create_party(PartyCreate(name="Tenant A", role="customer"))
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 1, 3),
            summary="Rent received",
            description="Rent received",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("250.00")),
                JournalLineIn(account_id=rent.id, amount=Decimal("-250.00")),
            ],
        )
    )


def _seed_ledger_with_accrual_plan(ledger_service: LedgerService) -> None:
    """Chart + one accrual plan that posts journal entries and obligations (#157)."""
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    party = ledger_service.create_party(
        PartyCreate(name="Tenant A", role="customer", is_active=True),
    )
    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Rent Plan 2026",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 28),
            amount=Decimal("1200.00"),
            summary_template="{plan} {month}",
            day_of_month=1,
        )
    )


_MINIMAL_PDF_BYTES = b"%PDF-1.1\n1 0 obj<<>>endobj trailer<<>>\n%%EOF"


def _seed_minimal_ledger_with_pdf_attachment(ledger_service: LedgerService) -> int:
    """Return attachment id after seeding one journal entry with a PDF attachment."""
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    entry = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 1, 3),
            summary="Rent received",
            description="Rent received",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("250.00")),
                JournalLineIn(account_id=rent.id, amount=Decimal("-250.00")),
            ],
        )
    )
    att = ledger_service.add_journal_entry_attachment(
        entry.id,
        file_bytes=_MINIMAL_PDF_BYTES,
        upload_filename="receipt.pdf",
        summary="Receipt",
        external_reference=None,
    )
    return att.id


def test_complete_export_round_trip_restores_row_counts(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        before = snapshot_table_counts(conn)
        zip_bytes = export_complete_snapshot(conn)

    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = {n for n in zf.namelist() if not n.endswith("/")}
    assert "metadata.json" in names
    for table in COMPLETE_TABLES:
        assert f"{table}.json" in names
    meta = json.loads(zf.read("metadata.json").decode("utf-8"))
    assert meta["export_type"] == "complete"
    assert meta["format_version"] == export_format_version()
    assert isinstance(meta["member_manifest"], list)
    assert len(meta["member_manifest"]) == len(names - {"metadata.json"})

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, zip_bytes)
        after = snapshot_table_counts(conn)

    assert after == before

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM journal_lines")
            assert Decimal(str(cur.fetchone()["s"])) == Decimal("0")


def test_complete_round_trip_preserves_import_batches_and_journal_link(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """#138: import_batches ride in complete exports and restore journal_entries.import_batch_id."""
    _seed_minimal_ledger(ledger_service)
    digest = bytes.fromhex("aa" * 32)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO import_batches (basename, content_sha256) VALUES (%s, %s) RETURNING id",
                    ("statement.csv", digest),
                )
                batch_id = int(cur.fetchone()["id"])
                cur.execute(
                    "UPDATE journal_entries SET import_batch_id = %s "
                    "WHERE id = (SELECT MIN(id) FROM journal_entries)",
                    (batch_id,),
                )
        with conn.cursor() as cur:
            cur.execute("SELECT import_batch_id FROM journal_entries ORDER BY id LIMIT 1")
            assert int(cur.fetchone()["import_batch_id"]) == batch_id
        before = snapshot_table_counts(conn)
        assert before["import_batches"] == 1
        zip_bytes = export_complete_snapshot(conn)

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, zip_bytes)
        after = snapshot_table_counts(conn)
        assert after["import_batches"] == 1
        with conn.cursor() as cur:
            cur.execute(
                "SELECT import_batch_id FROM journal_entries ORDER BY id LIMIT 1",
            )
            restored = cur.fetchone()["import_batch_id"]
            assert restored is not None
            assert int(restored) == batch_id


def test_complete_export_round_trip_restores_attachment_blob(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger_with_pdf_attachment(ledger_service)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, mime_type, blob FROM attachments ORDER BY id LIMIT 1")
            row = cur.fetchone()
            assert row is not None
            att_id = int(row["id"])
            mime = str(row["mime_type"])
            blob_raw = row["blob"]
            before_blob = bytes(blob_raw) if not isinstance(blob_raw, bytes) else blob_raw
        zip_bytes = export_complete_snapshot(conn)

    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    blob_path = attachment_blob_member_path(att_id, mime)
    names = {n for n in zf.namelist() if not n.endswith("/")}
    assert blob_path in names
    assert zf.read(blob_path) == before_blob

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, zip_bytes)
        with conn.cursor() as cur:
            cur.execute("SELECT blob FROM attachments WHERE id = %s", (att_id,))
            row2 = cur.fetchone()
            assert row2 is not None
            br = row2["blob"]
            after_blob = bytes(br) if not isinstance(br, bytes) else br
    assert after_blob == before_blob

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM journal_entry_attachments WHERE attachment_id = %s",
                (att_id,),
            )
            assert cur.fetchone() is not None


def test_import_format_v1_0_0_complete_without_attachment_members(
    monkeypatch: pytest.MonkeyPatch,
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """Archives from releases that only knew ``format_version`` 1.0.0 must still import (#80)."""
    import tallybadger.backup.snapshot as snap

    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_v1 = _repack_snapshot_for_format(export_complete_snapshot(conn), "1.0.0")

    meta = json.loads(zipfile.ZipFile(io.BytesIO(zip_v1)).read("metadata.json"))
    assert meta["format_version"] == "1.0.0"
    znames = {n for n in zipfile.ZipFile(io.BytesIO(zip_v1)).namelist() if not n.endswith("/")}
    assert "attachments.json" not in znames
    assert "settlement_events.json" in znames

    monkeypatch.setattr(snap, "FORMAT_VERSION_HISTORY", ("1.0.0", "1.1.0"))

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, zip_v1)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM attachments")
            assert int(cur.fetchone()["c"]) == 0


def test_import_rejects_unbalanced_journal(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)

    zin = zipfile.ZipFile(io.BytesIO(zip_bytes))
    try:
        meta = json.loads(zin.read("metadata.json").decode("utf-8"))
        members = {
            n: zin.read(n) for n in zin.namelist() if not n.endswith("/") and n != "metadata.json"
        }
    finally:
        zin.close()
    lines = json.loads(members["journal_lines.json"].decode("utf-8"))
    lines[0]["amount"] = "999.00"
    members["journal_lines.json"] = json.dumps(
        lines,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    corrupted = _rezip_table_members_with_metadata(
        members,
        {k: v for k, v in meta.items() if k != "member_manifest"},
    )

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SnapshotValidationError,
        match="do not balance",
    ):
        import_complete_snapshot(conn, corrupted)


def test_import_rejects_nonempty_database(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        pg_errors.UniqueViolation,
    ):
        import_complete_snapshot(conn, zip_bytes)


def test_import_rejects_unsupported_format_version(integration_db_url: str) -> None:
    _truncate_all_data(integration_db_url)
    _ensure_ledger_settings(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
    bad = _replace_metadata_only(zip_bytes, format_version="99.0.0")

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        UnsupportedFormatVersionError,
    ):
        import_complete_snapshot(conn, bad)


def test_import_accepts_prior_format_version_in_history(
    monkeypatch: pytest.MonkeyPatch,
    integration_db_url: str,
) -> None:
    """Import accepts format_version strings in the last four FORMAT_VERSION_HISTORY entries."""
    import tallybadger.backup.snapshot as snap

    _truncate_all_data(integration_db_url)
    _ensure_ledger_settings(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = _repack_snapshot_for_format(export_complete_snapshot(conn), "1.0.0")
    meta = json.loads(zipfile.ZipFile(io.BytesIO(zip_bytes)).read("metadata.json"))
    assert meta["format_version"] == "1.0.0"

    monkeypatch.setattr(snap, "FORMAT_VERSION_HISTORY", ("0.9.0", "1.0.0"))

    older = _replace_metadata_only(zip_bytes, format_version="0.9.0")

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, older)


def test_import_accepts_format_one_five_zero_settlement_events_archive(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """Archives with settlement_events.json (< 1.6.0) normalize to allocations-only on import (#153)."""
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
    legacy = _repack_snapshot_for_format(zip_bytes, "1.5.0")
    zf = zipfile.ZipFile(io.BytesIO(legacy))
    assert "settlement_events.json" in zf.namelist()
    assert "settlement_allocations.json" in zf.namelist()
    assert json.loads(zf.read("metadata.json").decode("utf-8"))["format_version"] == "1.5.0"

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, legacy)
        assert snapshot_table_counts(conn)["settlement_allocations"] == 0


def test_import_rejects_schema_version_mismatch(integration_db_url: str) -> None:
    _truncate_all_data(integration_db_url)
    _ensure_ledger_settings(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
    bad = _replace_metadata_only(zip_bytes, schema_version="000_never_applied")

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SchemaVersionMismatchError,
        match="not in this database's schema_migrations",
    ):
        import_complete_snapshot(conn, bad)


def test_import_accepts_older_recorded_schema_version(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """A snapshot stamped with an earlier applied migration may load on a newer database."""
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            applied = sorted(str(r["version"]) for r in cur.fetchall())
        if len(applied) < 2:
            pytest.skip("need at least two schema_migrations rows")
        older_schema = applied[-2]
        assert older_schema < current_schema_version(conn)
        zip_bytes = export_complete_snapshot(conn)
        before = snapshot_table_counts(conn)

    tweaked = _replace_metadata_only(zip_bytes, schema_version=older_schema)

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, tweaked)
        assert snapshot_table_counts(conn) == before


def test_import_rejects_snapshot_newer_than_target_schema(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
    too_new = _replace_metadata_only(
        zip_bytes,
        schema_version="zzz_future_migration_not_applied",
    )

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SchemaVersionMismatchError,
        match="snapshot is newer than this database",
    ):
        import_complete_snapshot(conn, too_new)


def test_backup_export_and_import_api_round_trip(
    integration_db_url: str,
    ledger_service: LedgerService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        _seed_minimal_ledger(ledger_service)

        client = TestClient(app)
        exp = client.post("/backup/export")
        assert exp.status_code == 200
        assert exp.headers["content-type"] == "application/zip"
        zip_bytes = exp.content

        _truncate_all_data(integration_db_url)

        imp = client.post(
            "/backup/import",
            files={"snapshot": ("snap.zip", zip_bytes, "application/zip")},
        )
        assert imp.status_code == 200
        assert imp.json() == {"status": "imported"}

        with connect(integration_db_url, row_factory=dict_row) as conn:
            counts = snapshot_table_counts(conn)
        assert counts["accounts"] >= 2
        assert counts["journal_entries"] == 1
        assert counts["journal_lines"] == 2
    finally:
        core_config.get_settings.cache_clear()


def test_backup_import_api_deprecation_warning_for_older_supported_format(
    integration_db_url: str,
    ledger_service: LedgerService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful import of an older supported format returns format_deprecation_warning (#202)."""
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        _seed_minimal_ledger(ledger_service)
        with connect(integration_db_url, row_factory=dict_row) as conn:
            zip_bytes = export_complete_snapshot(conn)
        older_fmt = "1.5.0"
        legacy_zip = _repack_snapshot_for_format(zip_bytes, older_fmt)

        _truncate_all_data(integration_db_url)

        client = TestClient(app)
        imp = client.post(
            "/backup/import",
            files={"snapshot": ("legacy.zip", legacy_zip, "application/zip")},
            data={"restore_mode": "erase-reload"},
        )
        assert imp.status_code == 200
        body = imp.json()
        assert body["status"] == "imported"
        warning = body["format_deprecation_warning"]
        expected = format_deprecation_warning(older_fmt)
        assert expected is not None
        assert warning == expected
        assert export_format_version() in warning
        assert older_fmt in warning
        assert oldest_supported_import_format_version() in warning
    finally:
        core_config.get_settings.cache_clear()


def test_backup_import_api_no_deprecation_on_unsupported_format(
    integration_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        _truncate_all_data(integration_db_url)
        _ensure_ledger_settings(integration_db_url)
        with connect(integration_db_url, row_factory=dict_row) as conn:
            zip_bytes = export_complete_snapshot(conn)
        bad = _replace_metadata_only(zip_bytes, format_version="99.0.0")

        client = TestClient(app)
        imp = client.post(
            "/backup/import",
            files={"snapshot": ("bad.zip", bad, "application/zip")},
        )
        assert imp.status_code == 400
        assert "format_deprecation_warning" not in imp.json()
    finally:
        core_config.get_settings.cache_clear()


def test_import_snapshot_returns_no_warning_for_current_format(
    integration_db_url: str,
) -> None:
    _truncate_all_data(integration_db_url)
    _ensure_ledger_settings(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
        warning = import_complete_snapshot(conn, zip_bytes, restore_mode="erase-reload")
    assert warning is None


def test_backup_import_api_reports_duplicate_key_in_detail(
    integration_db_url: str,
    ledger_service: LedgerService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP layer should classify unique violations for operators (#69)."""
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        _seed_minimal_ledger(ledger_service)
        client = TestClient(app)
        with connect(integration_db_url, row_factory=dict_row) as conn:
            zip_bytes = export_complete_snapshot(conn)
        imp = client.post(
            "/backup/import",
            files={"snapshot": ("snap.zip", zip_bytes, "application/zip")},
            data={"restore_mode": "abort"},
        )
        assert imp.status_code == 409
        body = imp.json()
        assert "detail" in body
        detail = body["detail"]
        assert isinstance(detail, str)
        assert "duplicate key" in detail.lower()
        assert "snapshot import" in detail.lower()
    finally:
        core_config.get_settings.cache_clear()


def test_backup_export_query_and_import_restore_mode_form(
    integration_db_url: str,
    ledger_service: LedgerService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        _seed_minimal_ledger(ledger_service)
        client = TestClient(app)
        with connect(integration_db_url, row_factory=dict_row) as conn:
            cfg = export_snapshot(conn, "configuration")
        exp = client.post("/backup/export?export_type=financial")
        assert exp.status_code == 200
        fin_zip = exp.content

        _truncate_all_data(integration_db_url)
        imp_cfg = client.post(
            "/backup/import",
            files={"snapshot": ("c.zip", cfg, "application/zip")},
            data={"restore_mode": "abort"},
        )
        assert imp_cfg.status_code == 200

        imp_fin = client.post(
            "/backup/import",
            files={"snapshot": ("f.zip", fin_zip, "application/zip")},
            data={"restore_mode": "abort"},
        )
        assert imp_fin.status_code == 200
        with connect(integration_db_url, row_factory=dict_row) as conn:
            assert snapshot_table_counts(conn)["journal_entries"] == 1
    finally:
        core_config.get_settings.cache_clear()


def test_backup_export_accepts_full_export_type_alias(
    integration_db_url: str,
    ledger_service: LedgerService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        _seed_minimal_ledger(ledger_service)
        client = TestClient(app)
        exp = client.post("/backup/export?export_type=full")
        assert exp.status_code == 200
        assert exp.headers["content-type"] == "application/zip"
        zf = zipfile.ZipFile(io.BytesIO(exp.content))
        meta = json.loads(zf.read("metadata.json").decode("utf-8"))
        assert meta["export_type"] == "complete"
        assert "tallybadger-complete-" in exp.headers.get("content-disposition", "")
    finally:
        core_config.get_settings.cache_clear()


def test_backup_export_rejects_unknown_export_type(
    integration_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        client = TestClient(app)
        exp = client.post("/backup/export?export_type=fu")
        assert exp.status_code == 400
        assert "unrecognized export_type" in exp.json()["detail"]
    finally:
        core_config.get_settings.cache_clear()


def test_configuration_export_has_only_configuration_members(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_snapshot(conn, "configuration")
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = {n for n in zf.namelist() if not n.endswith("/")}
    meta = json.loads(zf.read("metadata.json").decode("utf-8"))
    assert meta["export_type"] == "configuration"
    data_members = names - {"metadata.json"}
    assert data_members == {f"{t}.json" for t in CONFIGURATION_TABLES}


def test_financial_export_has_only_financial_members(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_snapshot(conn, "financial")
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = {n for n in zf.namelist() if not n.endswith("/")}
    meta = json.loads(zf.read("metadata.json").decode("utf-8"))
    assert meta["export_type"] == "financial"
    data_members = names - {"metadata.json"}
    assert data_members == {f"{t}.json" for t in financial_tables_for_format(export_format_version())}


def test_configuration_then_financial_two_step_import(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """Each import is atomic; financial relies on configuration already in the DB (#68)."""
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        config_zip = export_snapshot(conn, "configuration")
        fin_zip = export_snapshot(conn, "financial")
        full_counts = snapshot_table_counts(conn)

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_snapshot(conn, config_zip, restore_mode="abort")
        import_snapshot(conn, fin_zip, restore_mode="abort")
        assert snapshot_table_counts(conn) == full_counts


def test_financial_export_includes_accrual_plans(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """#157: accrual_plans ride in financial ZIPs (format_version 1.7.0+)."""
    _seed_ledger_with_accrual_plan(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_snapshot(conn, "financial")
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = {n for n in zf.namelist() if not n.endswith("/")}
    meta = json.loads(zf.read("metadata.json").decode("utf-8"))
    assert meta["format_version"] == export_format_version()
    assert "accrual_plans.json" in names
    plans = json.loads(zf.read("accrual_plans.json").decode("utf-8"))
    assert len(plans) == 1
    assert plans[0]["name"] == "Rent Plan 2026"


def test_configuration_then_financial_preserves_accrual_plan_links(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """#157: two-step restore keeps plans with plan-linked journals and obligations."""
    _seed_ledger_with_accrual_plan(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        config_zip = export_snapshot(conn, "configuration")
        fin_zip = export_snapshot(conn, "financial")
        full_counts = snapshot_table_counts(conn)
        assert full_counts["accrual_plans"] == 1
        assert full_counts["journal_entries"] >= 2
        assert full_counts["accrual_obligations"] >= 2

    zf = zipfile.ZipFile(io.BytesIO(fin_zip))
    assert "accrual_plans.json" in zf.namelist()
    zf.close()

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_snapshot(conn, config_zip, restore_mode="abort")
        import_snapshot(conn, fin_zip, restore_mode="abort")
        after = snapshot_table_counts(conn)

    assert after == full_counts
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM journal_entries
                WHERE accrual_plan_id IS NOT NULL
                """
            )
            assert int(cur.fetchone()["c"]) >= 2
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM accrual_obligations
                WHERE accrual_plan_id IS NOT NULL
                """
            )
            assert int(cur.fetchone()["c"]) >= 2


def test_financial_import_rejects_missing_account_reference(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        config_zip = export_snapshot(conn, "configuration")
        fin_zip = export_snapshot(conn, "financial")

    _truncate_all_data(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_snapshot(conn, config_zip, restore_mode="abort")

    zin = zipfile.ZipFile(io.BytesIO(fin_zip))
    try:
        meta = json.loads(zin.read("metadata.json").decode("utf-8"))
        members = {
            n: zin.read(n) for n in zin.namelist() if not n.endswith("/") and n != "metadata.json"
        }
    finally:
        zin.close()
    lines = json.loads(members["journal_lines.json"].decode("utf-8"))
    lines[0]["account_id"] = 999999
    members["journal_lines.json"] = json.dumps(
        lines,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    bad_fin = _rezip_table_members_with_metadata(
        members,
        {k: v for k, v in meta.items() if k != "member_manifest"},
    )

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SnapshotValidationError,
        match="not found in target database",
    ):
        import_snapshot(conn, bad_fin, restore_mode="abort")


def test_financial_import_rejects_import_batch_id_missing_everywhere(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """#138: import_batch_id must appear in import_batches.json or already exist in the DB."""
    _seed_minimal_ledger(ledger_service)
    digest = bytes.fromhex("dd" * 32)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO import_batches (basename, content_sha256) VALUES (%s, %s) RETURNING id",
                    ("batch-for-link.csv", digest),
                )
                batch_id = int(cur.fetchone()["id"])
                cur.execute(
                    "UPDATE journal_entries SET import_batch_id = %s "
                    "WHERE id = (SELECT MIN(id) FROM journal_entries)",
                    (batch_id,),
                )
        config_zip = export_snapshot(conn, "configuration")
        fin_zip = export_snapshot(conn, "financial")

    _truncate_all_data(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_snapshot(conn, config_zip, restore_mode="abort")

    zin = zipfile.ZipFile(io.BytesIO(fin_zip))
    try:
        meta = json.loads(zin.read("metadata.json").decode("utf-8"))
        members = {
            n: zin.read(n) for n in zin.namelist() if not n.endswith("/") and n != "metadata.json"
        }
    finally:
        zin.close()
    entries = json.loads(members["journal_entries.json"].decode("utf-8"))
    entries[0]["import_batch_id"] = 999999
    members["journal_entries.json"] = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    bad_fin = _rezip_table_members_with_metadata(
        members,
        {k: v for k, v in meta.items() if k != "member_manifest"},
    )

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SnapshotValidationError,
        match="import_batch_id",
    ):
        import_snapshot(conn, bad_fin, restore_mode="abort")


def test_import_abort_rejects_conflicting_financial_rows(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        fin_zip = export_snapshot(conn, "financial")

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        pg_errors.UniqueViolation,
    ):
        import_snapshot(conn, fin_zip, restore_mode="abort")


def test_backup_import_api_rejects_legacy_erase_reload_spelling(
    integration_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        _truncate_all_data(integration_db_url)
        with connect(integration_db_url, row_factory=dict_row) as conn:
            zip_bytes = export_complete_snapshot(conn)
        client = TestClient(app)
        imp = client.post(
            "/backup/import",
            files={"snapshot": ("snap.zip", zip_bytes, "application/zip")},
            data={"restore_mode": "erase_reload"},
        )
        assert imp.status_code == 400
        assert "unrecognized restore_mode" in imp.json()["detail"]
    finally:
        core_config.get_settings.cache_clear()


def test_backup_import_api_rejects_invalid_restore_mode(
    integration_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()
    try:
        _truncate_all_data(integration_db_url)
        with connect(integration_db_url, row_factory=dict_row) as conn:
            zip_bytes = export_complete_snapshot(conn)
        client = TestClient(app)
        imp = client.post(
            "/backup/import",
            files={"snapshot": ("snap.zip", zip_bytes, "application/zip")},
            data={"restore_mode": "erase-spice-girls-music"},
        )
        assert imp.status_code == 400
        detail = imp.json()["detail"]
        assert "unrecognized restore_mode" in detail
    finally:
        core_config.get_settings.cache_clear()


def test_erase_reload_rejects_financial_only_snapshot(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        fin_zip = export_snapshot(conn, "financial")

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SnapshotValidationError,
        match="erase-reload cannot import a financial-only",
    ):
        import_snapshot(conn, fin_zip, restore_mode="erase-reload")


def test_erase_reload_truncates_all_then_loads_complete_snapshot(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
        before = snapshot_table_counts(conn)

    extra = ledger_service.create_account(AccountCreate(name="Noise CoA", type="asset"))
    assert extra.id is not None
    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_snapshot(conn, zip_bytes, restore_mode="erase-reload")
        after = snapshot_table_counts(conn)

    assert after == before


def test_import_overwrite_replaces_financial_scope(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        fin_zip = export_snapshot(conn, "financial")
        before = snapshot_table_counts(conn)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_snapshot(conn, fin_zip, restore_mode="overwrite")
        assert snapshot_table_counts(conn) == before


def test_import_rejects_member_set_mismatch_for_export_type(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    """metadata export_type must match the ZIP table set."""
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
    bad = _replace_metadata_only(zip_bytes, export_type="configuration")

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        IncompleteSnapshotError,
        match="does not match export_type",
    ):
        import_snapshot(conn, bad, restore_mode="abort")


def test_import_rejects_zip_with_extra_member(integration_db_url: str) -> None:
    _truncate_all_data(integration_db_url)
    _ensure_ledger_settings(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
    zin = zipfile.ZipFile(io.BytesIO(zip_bytes))
    try:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name in zin.namelist():
                if name.endswith("/"):
                    continue
                zout.writestr(name, zin.read(name))
            zout.writestr("surprise.json", b"{}")
    finally:
        zin.close()

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SnapshotIntegrityError,
        match="unexpected ZIP members",
    ):
        import_complete_snapshot(conn, out.getvalue())


def test_cheque_default_accounts_round_trip_through_complete_snapshot(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """#105: cheque last-used defaults survive complete export/import."""
    cash = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent", type="expense"))

    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ledger_settings
                    SET default_cheque_credit_account_id = %s,
                        default_cheque_debit_account_id = %s
                    WHERE id = 1
                    """,
                    (cash.id, rent.id),
                )

    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_complete_snapshot(conn)

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, archive)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT default_cheque_credit_account_id, default_cheque_debit_account_id
                FROM ledger_settings
                WHERE id = 1
                """,
            )
            row = cur.fetchone()
    assert row is not None
    assert row["default_cheque_credit_account_id"] == cash.id
    assert row["default_cheque_debit_account_id"] == rent.id


def test_snapshot_rejects_cheque_default_pointing_at_missing_account(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """#105: the snapshot FK validator catches dangling cheque-default references."""
    cash = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent", type="expense"))
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ledger_settings
                    SET default_cheque_credit_account_id = %s,
                        default_cheque_debit_account_id = %s
                    WHERE id = 1
                    """,
                    (cash.id, rent.id),
                )

    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_snapshot(conn, "configuration")

    # Tamper: drop the credit-default account from accounts.json so it no longer resolves.
    zin = zipfile.ZipFile(io.BytesIO(archive))
    try:
        names = [n for n in zin.namelist() if not n.endswith("/")]
        table_members: dict[str, bytes] = {n: zin.read(n) for n in names if n != "metadata.json"}
        metadata = json.loads(zin.read("metadata.json").decode("utf-8"))
    finally:
        zin.close()
    accounts_rows = json.loads(table_members["accounts.json"].decode("utf-8"))
    accounts_rows = [r for r in accounts_rows if int(r["id"]) != cash.id]
    table_members["accounts.json"] = json.dumps(
        accounts_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    tampered = _rezip_table_members_with_metadata(table_members, metadata)

    _truncate_all_data(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SnapshotValidationError,
        match="default_cheque_credit_account_id",
    ):
        import_snapshot(conn, tampered)


def test_filter_presets_round_trip_through_configuration_snapshot(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """#107: named filter presets survive a configuration export/import."""
    from tallybadger.ledger.journal_entry_filter_preset_service import (
        JournalEntryFilterPresetService,
    )
    from tallybadger.ledger.models import JournalEntryFilterPresetDefinition

    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    _ = revenue

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    preset_service = JournalEntryFilterPresetService(
        connection_factory=connection_factory,
    )
    preset_service.create_preset(
        name="Cash only",
        definition=JournalEntryFilterPresetDefinition(
            account_ids=[cash.id],
            amount_low=0,
            amount_high=1000,
            from_date="now-7d",
            to_date="now",
        ),
    )

    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_snapshot(conn, "configuration")

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_snapshot(conn, archive)

    restored = preset_service.list_presets()
    assert [p.name for p in restored] == ["Cash only"]
    assert restored[0].definition.account_ids == [cash.id]
    assert restored[0].definition.amount_high == 1000
    assert restored[0].definition.from_date == "now-7d"
    assert restored[0].definition.to_date == "now"


def test_filter_preset_with_missing_account_id_rejected_by_import(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """#107: embedded ids in preset definitions are validated against the archive."""
    from tallybadger.ledger.journal_entry_filter_preset_service import (
        JournalEntryFilterPresetService,
    )
    from tallybadger.ledger.models import JournalEntryFilterPresetDefinition

    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    preset_service = JournalEntryFilterPresetService(connection_factory=connection_factory)
    preset_service.create_preset(
        name="Refs cash",
        definition=JournalEntryFilterPresetDefinition(account_ids=[cash.id]),
    )

    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_snapshot(conn, "configuration")

    zin = zipfile.ZipFile(io.BytesIO(archive))
    try:
        names = [n for n in zin.namelist() if not n.endswith("/")]
        table_members: dict[str, bytes] = {
            n: zin.read(n) for n in names if n != "metadata.json"
        }
        metadata = json.loads(zin.read("metadata.json").decode("utf-8"))
    finally:
        zin.close()
    accounts_rows = json.loads(table_members["accounts.json"].decode("utf-8"))
    accounts_rows = [r for r in accounts_rows if int(r["id"]) != cash.id]
    table_members["accounts.json"] = json.dumps(
        accounts_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    tampered = _rezip_table_members_with_metadata(table_members, metadata)

    _truncate_all_data(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SnapshotValidationError,
        match="account_ids",
    ):
        import_snapshot(conn, tampered)


def test_cheque_register_filter_presets_round_trip_through_configuration_snapshot(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """#196: cheque register presets survive configuration export/import."""
    from tallybadger.ledger.cheque_register_filter_preset_service import (
        ChequeRegisterFilterPresetService,
    )
    from tallybadger.ledger.models import (
        ChequeRegisterFilterPresetDefinition,
        ChequeRegisterFilterPresetSortKey,
    )

    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    expense = ledger_service.create_account(AccountCreate(name="Rent", type="expense"))

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    preset_service = ChequeRegisterFilterPresetService(
        connection_factory=connection_factory,
    )
    preset_service.create_preset(
        name="Open chequing",
        definition=ChequeRegisterFilterPresetDefinition(
            status="open",
            credit_account_ids=[cash.id],
            sort=[ChequeRegisterFilterPresetSortKey(field="amount", direction="desc")],
        ),
    )

    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_snapshot(conn, "configuration")

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_snapshot(conn, archive)

    restored = preset_service.list_presets()
    assert [p.name for p in restored] == ["Open chequing"]
    assert restored[0].definition.credit_account_ids == [cash.id]
    assert restored[0].definition.sort[0].field == "amount"
    assert expense.id not in restored[0].definition.credit_account_ids


def test_cheque_register_filter_preset_missing_account_rejected_by_import(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """#196: embedded account ids in cheque preset definitions are validated."""
    from tallybadger.ledger.cheque_register_filter_preset_service import (
        ChequeRegisterFilterPresetService,
    )
    from tallybadger.ledger.models import ChequeRegisterFilterPresetDefinition

    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    preset_service = ChequeRegisterFilterPresetService(connection_factory=connection_factory)
    preset_service.create_preset(
        name="Refs cash",
        definition=ChequeRegisterFilterPresetDefinition(credit_account_ids=[cash.id]),
    )

    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_snapshot(conn, "configuration")

    zin = zipfile.ZipFile(io.BytesIO(archive))
    try:
        names = [n for n in zin.namelist() if not n.endswith("/")]
        table_members: dict[str, bytes] = {
            n: zin.read(n) for n in names if n != "metadata.json"
        }
        metadata = json.loads(zin.read("metadata.json").decode("utf-8"))
    finally:
        zin.close()
    accounts_rows = json.loads(table_members["accounts.json"].decode("utf-8"))
    accounts_rows = [r for r in accounts_rows if int(r["id"]) != cash.id]
    table_members["accounts.json"] = json.dumps(
        accounts_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    tampered = _rezip_table_members_with_metadata(table_members, metadata)

    _truncate_all_data(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SnapshotValidationError,
        match="credit_account_ids",
    ):
        import_snapshot(conn, tampered)


def test_financial_export_excludes_cheque_register_filter_presets(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """#196: financial-only archives do not carry cheque register presets."""
    from tallybadger.ledger.cheque_register_filter_preset_service import (
        ChequeRegisterFilterPresetService,
    )
    from tallybadger.ledger.models import ChequeRegisterFilterPresetDefinition

    _ = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    preset_service = ChequeRegisterFilterPresetService(connection_factory=connection_factory)
    preset_service.create_preset(
        name="Any",
        definition=ChequeRegisterFilterPresetDefinition(status="open"),
    )

    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_snapshot(conn, "financial")

    zin = zipfile.ZipFile(io.BytesIO(archive))
    try:
        names = {n for n in zin.namelist() if not n.endswith("/")}
    finally:
        zin.close()
    assert "cheque_register_filter_presets.json" not in names
