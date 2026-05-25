"""Integration tests for GET /journal-entries sort (#201)."""

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
from tallybadger.ledger.models import (
    AccountCreate,
    JournalEntryWrite,
    JournalLineIn,
    PartyCreate,
)
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


def _seed_three_entries(ledger_service: LedgerService) -> tuple[int, int, int]:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    expense = ledger_service.create_account(AccountCreate(name="Repairs", type="expense"))
    payable = ledger_service.create_account(AccountCreate(name="Payable", type="liability"))
    party_a = ledger_service.create_party(PartyCreate(name="Alpha", role="customer"))
    party_b = ledger_service.create_party(PartyCreate(name="Bravo", role="vendor"))

    small = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 1),
            summary="alpha small",
            description="alpha small",
            lines=[
                JournalLineIn(account_id=cash.id, party_id=party_a.id, amount=Decimal("50.00")),
                JournalLineIn(account_id=revenue.id, party_id=party_a.id, amount=Decimal("-50.00")),
            ],
        )
    )
    medium = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 2),
            summary="bravo medium",
            description="bravo medium",
            lines=[
                JournalLineIn(account_id=expense.id, party_id=party_b.id, amount=Decimal("150.00")),
                JournalLineIn(account_id=payable.id, party_id=party_b.id, amount=Decimal("-150.00")),
            ],
        )
    )
    large = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 3),
            summary="alpha large",
            description="alpha large",
            lines=[
                JournalLineIn(account_id=cash.id, party_id=party_a.id, amount=Decimal("500.00")),
                JournalLineIn(account_id=revenue.id, party_id=party_a.id, amount=Decimal("-500.00")),
            ],
        )
    )
    return small.id, medium.id, large.id


def test_list_journal_entries_default_sort(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    small_id, medium_id, large_id = _seed_three_entries(ledger_service)

    rows = api_client.get("/journal-entries", params={"limit": 10}).json()
    assert [row["id"] for row in rows] == [large_id, medium_id, small_id]


def test_list_journal_entries_amount_sort_changes_first_page(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    small_id, medium_id, large_id = _seed_three_entries(ledger_service)

    by_amount_asc = api_client.get(
        "/journal-entries",
        params={"sort": ["amount:asc"], "limit": 10},
    ).json()
    assert [row["id"] for row in by_amount_asc] == [small_id, medium_id, large_id]

    by_amount_desc = api_client.get(
        "/journal-entries",
        params={"sort": ["amount:desc"], "limit": 10},
    ).json()
    assert [row["id"] for row in by_amount_desc] == [large_id, medium_id, small_id]


def test_list_journal_entries_multi_key_sort(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    small_id, medium_id, large_id = _seed_three_entries(ledger_service)

    by_summary_then_amount = api_client.get(
        "/journal-entries",
        params={"sort": ["summary:asc", "amount:desc"], "limit": 10},
    ).json()
    assert [row["id"] for row in by_summary_then_amount] == [large_id, small_id, medium_id]


def test_list_journal_entries_sort_with_date_filter(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    small_id, medium_id, _large_id = _seed_three_entries(ledger_service)

    rows = api_client.get(
        "/journal-entries",
        params={
            "from_date": "2026-06-01",
            "to_date": "2026-06-02",
            "sort": ["amount:desc"],
            "limit": 10,
        },
    ).json()
    assert [row["id"] for row in rows] == [medium_id, small_id]


def test_list_journal_entries_invalid_sort_returns_422(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    _seed_three_entries(ledger_service)

    bad_field = api_client.get("/journal-entries", params={"sort": ["not_a_field:asc"]})
    assert bad_field.status_code == 422
    assert "not_a_field" in bad_field.json()["detail"]

    bad_direction = api_client.get("/journal-entries", params={"sort": ["amount:up"]})
    assert bad_direction.status_code == 422
    assert "amount" in bad_direction.json()["detail"]


def test_list_journal_entries_appends_id_desc_when_missing_from_client_sort(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash B", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent B", type="revenue"))
    same_day = date(2026, 7, 15)
    first = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=same_day,
            summary="tie a",
            description="tie a",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("10.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-10.00")),
            ],
        )
    )
    second = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=same_day,
            summary="tie b",
            description="tie b",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("20.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-20.00")),
            ],
        )
    )
    assert second.id > first.id

    rows = api_client.get(
        "/journal-entries",
        params={"from_date": "2026-07-15", "to_date": "2026-07-15", "sort": ["entry_date:asc"]},
    ).json()
    # Client sort omits id; server appends id DESC (higher id wins ties, same as cheques #193).
    assert [row["id"] for row in rows] == [second.id, first.id]
