"""Integration tests for scripts/tbload directory input (#207)."""

from __future__ import annotations

import io
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
from tallybadger.backup.snapshot import export_complete_snapshot, snapshot_table_counts
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn, PartyCreate
from tallybadger.ledger.service import LedgerService
from tallybadger.main import app

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[1]
TBLOAD_PATH = REPO_ROOT / "scripts" / "tbload"


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


def _expand_zip_to_directory(zip_bytes: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        archive.extractall(destination)


@pytest.fixture
def tbload_api_base_url(integration_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        pytest.fail("API server did not become ready for tbload integration test")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        core_config.get_settings.cache_clear()


def test_tbload_directory_input_imports_expanded_snapshot(
    integration_db_url: str,
    ledger_service: LedgerService,
    tbload_api_base_url: str,
    tmp_path: Path,
) -> None:
    _seed_minimal_ledger(ledger_service)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        zip_bytes = export_complete_snapshot(conn)

    expanded_dir = tmp_path / "seed"
    expanded_dir.mkdir()
    _expand_zip_to_directory(zip_bytes, expanded_dir)
    assert (expanded_dir / "metadata.json").is_file()

    _truncate_all_data(integration_db_url)
    _ensure_ledger_settings(integration_db_url)

    input_label = "seed"
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(TBLOAD_PATH),
            "--mode",
            "erase-reload",
            "-i",
            input_label,
            "--base-url",
            tbload_api_base_url,
        ],
        capture_output=True,
        check=False,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert b"Restore finished successfully." in proc.stdout

    with connect(integration_db_url, row_factory=dict_row) as conn:
        counts = snapshot_table_counts(conn)
    assert counts["accounts"] >= 2
    assert counts["journal_entries"] == 1
    assert counts["journal_lines"] == 2
