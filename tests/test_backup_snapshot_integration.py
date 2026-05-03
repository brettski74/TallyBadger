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

from tallybadger.backup.errors import (
    SchemaVersionMismatchError,
    SnapshotIntegrityError,
    SnapshotValidationError,
    TargetNotEmptyError,
    UnsupportedFormatVersionError,
)
from tallybadger.backup.snapshot import (
    COMPLETE_TABLES,
    export_complete_snapshot,
    import_complete_snapshot,
    snapshot_table_counts,
)
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn, PartyCreate
from tallybadger.ledger.service import LedgerService

pytestmark = pytest.mark.integration


def _truncate_all_data(integration_db_url: str) -> None:
    with connect(integration_db_url) as conn:
        with conn.transaction():
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
    assert meta["format_version"] == "1.0.0"
    assert isinstance(meta["member_manifest"], list)
    assert len(meta["member_manifest"]) == len(COMPLETE_TABLES)

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        import_complete_snapshot(conn, zip_bytes)
        after = snapshot_table_counts(conn)

    assert after == before

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM journal_lines")
            assert Decimal(str(cur.fetchone()["s"])) == Decimal("0")


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
        match="not balanced",
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
        TargetNotEmptyError,
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


def test_import_rejects_schema_version_mismatch(integration_db_url: str) -> None:
    _truncate_all_data(integration_db_url)
    _ensure_ledger_settings(integration_db_url)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)
    bad = _replace_metadata_only(zip_bytes, schema_version="000_never_applied")

    _truncate_all_data(integration_db_url)

    with connect(integration_db_url, row_factory=dict_row) as conn, pytest.raises(
        SchemaVersionMismatchError,
    ):
        import_complete_snapshot(conn, bad)


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
