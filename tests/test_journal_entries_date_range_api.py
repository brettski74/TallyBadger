"""Integration tests for journal entry list date math query params (#133)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.main import app
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn
from tallybadger.ledger.service import LedgerService

pytestmark = pytest.mark.integration


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
def clean_database(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
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


@pytest.fixture
def ledger_service(integration_db_url: str) -> LedgerService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return LedgerService(connection_factory=connection_factory)


@pytest.fixture
def api_client(ledger_service: LedgerService) -> Iterator[TestClient]:
    app.dependency_overrides[get_ledger_service] = lambda: ledger_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_journal_entries_resolves_iso_date_strings(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash DR", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent DR", type="revenue"))
    for entry_date, summary in (
        (date(2026, 5, 1), "early may"),
        (date(2026, 5, 6), "anchor day"),
        (date(2026, 6, 1), "june"),
    ):
        ledger_service.create_entry(
            JournalEntryWrite(
                entry_date=entry_date,
                summary=summary,
                description=summary,
                lines=[
                    JournalLineIn(account_id=cash.id, amount=Decimal("1.00")),
                    JournalLineIn(account_id=revenue.id, amount=Decimal("-1.00")),
                ],
            )
        )

    response = api_client.get(
        "/journal-entries",
        params={
            "from_date": "2026-05-01",
            "to_date": "2026-05-06",
        },
    )
    assert response.status_code == 200
    summaries = {row["summary"] for row in response.json()}
    assert summaries == {"early may", "anchor day"}


def test_list_journal_entries_resolves_date_math_with_anchor(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash DM", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent DM", type="revenue"))
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 6),
            summary="mtd hit",
            description="mtd hit",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("1.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-1.00")),
            ],
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 4, 30),
            summary="before mtd",
            description="before mtd",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("1.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-1.00")),
            ],
        )
    )

    response = api_client.get(
        "/journal-entries",
        params={
            "from_date": "now/M",
            "to_date": "now",
            "anchor": "2026-05-06T12:00:00Z",
        },
    )
    assert response.status_code == 200
    summaries = {row["summary"] for row in response.json()}
    assert summaries == {"mtd hit"}
