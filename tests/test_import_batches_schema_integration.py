"""Integration tests: import_batches table and journal_entries.import_batch_id (#134)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator

import pytest
from psycopg import connect
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations

pytestmark = pytest.mark.integration

_ZERO_SHA256 = hashlib.sha256(b"").digest()


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
def clean_import_batches(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE journal_entry_filter_presets, import_templates,
                      journal_lines, journal_entry_attachments,
                      attachments, journal_entries, import_batches,
                      accrual_plans, party_match_patterns, parties, accounts, cel_rule_sets
                    RESTART IDENTITY CASCADE
                    """
                )
                cur.execute(
                    "INSERT INTO ledger_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
                )
    yield


def test_import_batches_reject_blank_basename(integration_db_url: str) -> None:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            with pytest.raises(pg_errors.CheckViolation):
                cur.execute(
                    "INSERT INTO import_batches (basename, content_sha256) VALUES (%s, %s)",
                    ("   ", _ZERO_SHA256),
                )


def test_active_basename_unique_case_insensitive(integration_db_url: str) -> None:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO import_batches (basename, content_sha256) VALUES (%s, %s)",
                    ("Bank-2024.csv", _ZERO_SHA256),
                )
                with pytest.raises(pg_errors.UniqueViolation):
                    with conn.transaction():
                        cur.execute(
                            "INSERT INTO import_batches (basename, content_sha256) VALUES (%s, %s)",
                            ("bank-2024.csv", hashlib.sha256(b"other").digest()),
                        )


def test_inactive_batch_allows_same_basename_ci(integration_db_url: str) -> None:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO import_batches (basename, content_sha256) VALUES (%s, %s)",
                    ("Stmt.csv", _ZERO_SHA256),
                )
                cur.execute("UPDATE import_batches SET is_active = FALSE WHERE basename = %s", ("Stmt.csv",))
                cur.execute(
                    "INSERT INTO import_batches (basename, content_sha256) VALUES (%s, %s)",
                    ("stmt.csv", hashlib.sha256(b"reload").digest()),
                )
                cur.execute("SELECT COUNT(*) AS c FROM import_batches")
                assert int(cur.fetchone()["c"]) == 2


def test_journal_entry_may_reference_import_batch(integration_db_url: str) -> None:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO accounts (name, type)
                    VALUES ('Cash', 'asset'), ('Income', 'revenue')
                    """
                )
                cur.execute(
                    "INSERT INTO import_batches (basename, content_sha256) VALUES (%s, %s) RETURNING id",
                    ("Rent.csv", _ZERO_SHA256),
                )
                batch_id = int(cur.fetchone()["id"])
                cur.execute(
                    """
                    INSERT INTO journal_entries (entry_date, summary, import_batch_id)
                    VALUES (DATE '2026-01-01', 'imported row', %s)
                    RETURNING id
                    """,
                    (batch_id,),
                )
                entry_id = int(cur.fetchone()["id"])
                cur.execute(
                    """
                    INSERT INTO journal_lines (entry_id, account_id, amount)
                    VALUES (%s, 1, '100.00'), (%s, 2, '-100.00')
                    """,
                    (entry_id, entry_id),
                )
                cur.execute(
                    "SELECT import_batch_id FROM journal_entries WHERE id = %s",
                    (entry_id,),
                )
                assert int(cur.fetchone()["import_batch_id"]) == batch_id


def test_journal_entry_rejects_unknown_import_batch_id(integration_db_url: str) -> None:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO accounts (name, type) VALUES ('Cash', 'asset'), ('Income', 'revenue')"
                )
                with pytest.raises(pg_errors.ForeignKeyViolation):
                    with conn.transaction():
                        cur.execute(
                            """
                            INSERT INTO journal_entries (entry_date, summary, import_batch_id)
                            VALUES (DATE '2026-01-02', 'bad fk', 999999)
                            """
                        )
