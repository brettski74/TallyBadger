"""Integration tests for scripts/tbsave (#215)."""

from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import uvicorn
from psycopg import connect
from psycopg.rows import dict_row

import tallybadger.core.config as core_config
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn, PartyCreate
from tallybadger.ledger.service import LedgerService
from tallybadger.main import app

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[1]
TBSAVE_PATH = REPO_ROOT / "scripts" / "tbsave"


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


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def tbsave_api_base_url(integration_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    if shutil.which("curl") is None:
        pytest.skip("curl not on PATH")

    monkeypatch.setenv("TALLYBADGER_DATABASE_URL", integration_db_url)
    core_config.get_settings.cache_clear()

    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        health = subprocess.run(  # noqa: S603
            ["curl", "-fsS", f"{base_url}/health"],
            capture_output=True,
            check=False,
        )
        if health.returncode == 0:
            break
        time.sleep(0.1)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("API server did not become ready for tbsave integration test")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        core_config.get_settings.cache_clear()


def test_tbsave_writes_zip_to_file(
    ledger_service: LedgerService,
    tbsave_api_base_url: str,
    tmp_path: Path,
) -> None:
    _seed_minimal_ledger(ledger_service)
    out_file = tmp_path / "snap.zip"
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(TBSAVE_PATH),
            "-o",
            str(out_file),
            "--base-url",
            tbsave_api_base_url,
            "-q",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert out_file.is_file()
    with zipfile.ZipFile(out_file) as archive:
        meta = json.loads(archive.read("metadata.json").decode("utf-8"))
    assert meta["export_type"] == "complete"


def test_tbsave_stdout_mode_emits_zip_bytes(
    ledger_service: LedgerService,
    tbsave_api_base_url: str,
) -> None:
    _seed_minimal_ledger(ledger_service)
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(TBSAVE_PATH),
            "--base-url",
            tbsave_api_base_url,
            "-q",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert proc.stdout[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(proc.stdout)) as archive:
        meta = json.loads(archive.read("metadata.json").decode("utf-8"))
    assert meta["export_type"] == "complete"


def test_tbsave_full_scope_uses_api_alias(
    ledger_service: LedgerService,
    tbsave_api_base_url: str,
    tmp_path: Path,
) -> None:
    _seed_minimal_ledger(ledger_service)
    out_file = tmp_path / "snap.zip"
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(TBSAVE_PATH),
            "-s",
            "full",
            "-o",
            str(out_file),
            "--base-url",
            tbsave_api_base_url,
            "-q",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    with zipfile.ZipFile(out_file) as archive:
        meta = json.loads(archive.read("metadata.json").decode("utf-8"))
    assert meta["export_type"] == "complete"


def test_tbsave_directory_output_uses_default_filename(
    ledger_service: LedgerService,
    tbsave_api_base_url: str,
    tmp_path: Path,
) -> None:
    _seed_minimal_ledger(ledger_service)
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(TBSAVE_PATH),
            "-s",
            "financial",
            "-o",
            str(out_dir),
            "--base-url",
            tbsave_api_base_url,
            "-q",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    zips = list(out_dir.glob("tallybadger-financial-*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as archive:
        meta = json.loads(archive.read("metadata.json").decode("utf-8"))
    assert meta["export_type"] == "financial"
