"""Integration tests: journal list accrual_plan_ids includes settlement JEs (#249)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import hashlib
import os

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import (
    AccountCreate,
    AccrualPlanCreate,
    JournalEntryWrite,
    JournalLineIn,
    LedgerSettingsUpdate,
    PartyCreate,
    SettlementAllocationIn,
    SettlementWrite,
)
from tallybadger.ledger.service import LedgerService
from tallybadger.main import app

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
def clean_tables(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE
                      settlement_allocations,
                      accrual_obligations,
                      journal_entry_review_messages,
                      journal_lines,
                      journal_entries,
                      import_batches,
                      accrual_plans,
                      parties,
                      accounts,
                      cel_rule_sets
                    RESTART IDENTITY CASCADE
                    """,
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


def _list_entry_ids(api_client: TestClient, *, accrual_plan_ids: list[int]) -> list[int]:
    response = api_client.get(
        "/journal-entries",
        params=[("accrual_plan_ids", str(pid)) for pid in accrual_plan_ids],
    )
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()]


def _setup_rent_accrual(
    ledger_service: LedgerService,
    *,
    plan_name: str = "July rent",
    party_name: str = "Pamela Tenant",
    start_date: date = date(2026, 7, 1),
    end_date: date = date(2026, 7, 31),
) -> tuple[int, int, int, int, int, int]:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id),
    )
    return _add_rent_plan(
        ledger_service,
        cash_id=cash.id,
        ar_id=ar.id,
        rent_id=rent.id,
        plan_name=plan_name,
        party_name=party_name,
        start_date=start_date,
        end_date=end_date,
    )


def _add_rent_plan(
    ledger_service: LedgerService,
    *,
    cash_id: int,
    ar_id: int,
    rent_id: int,
    plan_name: str,
    party_name: str,
    start_date: date,
    end_date: date,
) -> tuple[int, int, int, int, int, int]:
    party = ledger_service.create_party(
        PartyCreate(name=party_name, role="customer", is_active=True),
    )
    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name=plan_name,
            direction="revenue",
            party_id=party.id,
            target_account_id=rent_id,
            frequency="monthly_day",
            start_date=start_date,
            end_date=end_date,
            amount=Decimal("1500.00"),
            summary_template="{plan}",
            day_of_month=1,
        ),
    )
    ob = ledger_service.list_open_obligations(party.id)[0]
    assert ob.source_entry_id is not None
    return party.id, cash_id, ar_id, plan.id, ob.id, ob.source_entry_id


def test_accrual_plan_filter_includes_non_collapsed_settlement_je(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    party_id, cash_id, _ar_id, plan_id, ob_id, accrual_entry_id = _setup_rent_accrual(
        ledger_service,
    )
    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_id,
            settlement_type="receipt",
            event_date=date(2026, 7, 15),
            amount=Decimal("1500.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_id, amount=Decimal("1500.00"))],
            note=None,
        ),
    )
    assert result.entry_id != accrual_entry_id

    ids = _list_entry_ids(api_client, accrual_plan_ids=[plan_id])
    assert sorted(ids) == sorted([accrual_entry_id, result.entry_id])


def test_accrual_plan_filter_excludes_other_plan_settlements(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    party_id, cash_id, _ar_id, plan_a_id, ob_a_id, accrual_a_id = _setup_rent_accrual(
        ledger_service,
        plan_name="Plan A",
    )
    settle_a = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_id,
            settlement_type="receipt",
            event_date=date(2026, 7, 15),
            amount=Decimal("1500.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_a_id, amount=Decimal("1500.00"))],
            note=None,
        ),
    )

    rent_id = next(a.id for a in ledger_service.list_accounts() if a.name == "Rent Revenue")
    party_b, _cash_b, _ar_b, plan_b_id, ob_b_id, accrual_b_id = _add_rent_plan(
        ledger_service,
        cash_id=cash_id,
        ar_id=_ar_id,
        rent_id=rent_id,
        plan_name="Plan B",
        party_name="Bob Tenant",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )
    settle_b = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_b,
            settlement_type="receipt",
            event_date=date(2026, 8, 15),
            amount=Decimal("1500.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_b_id, amount=Decimal("1500.00"))],
            note=None,
        ),
    )

    ids = _list_entry_ids(api_client, accrual_plan_ids=[plan_a_id])
    assert sorted(ids) == sorted([accrual_a_id, settle_a.entry_id])
    assert settle_b.entry_id not in ids
    assert accrual_b_id not in ids


def test_accrual_plan_filter_multiple_plans_no_duplicate_ids(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    party_id, cash_id, _ar_id, plan_a_id, ob_a_id, accrual_a_id = _setup_rent_accrual(
        ledger_service,
        plan_name="Plan A",
    )
    settle_a = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_id,
            settlement_type="receipt",
            event_date=date(2026, 7, 15),
            amount=Decimal("1500.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_a_id, amount=Decimal("1500.00"))],
            note=None,
        ),
    )

    rent_id = next(a.id for a in ledger_service.list_accounts() if a.name == "Rent Revenue")
    party_b, _cash_b, _ar_b, plan_b_id, ob_b_id, accrual_b_id = _add_rent_plan(
        ledger_service,
        cash_id=cash_id,
        ar_id=_ar_id,
        rent_id=rent_id,
        plan_name="Plan B",
        party_name="Bob Tenant",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )
    settle_b = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_b,
            settlement_type="receipt",
            event_date=date(2026, 8, 15),
            amount=Decimal("1500.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_b_id, amount=Decimal("1500.00"))],
            note=None,
        ),
    )

    ids = _list_entry_ids(api_client, accrual_plan_ids=[plan_a_id, plan_b_id])
    assert len(ids) == len(set(ids))
    assert sorted(ids) == sorted(
        [accrual_a_id, settle_a.entry_id, accrual_b_id, settle_b.entry_id],
    )


def test_accrual_plan_filter_includes_csv_import_settlement_je(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, plan_id, obligation_id, accrual_entry_id = _setup_rent_accrual(
        ledger_service,
    )
    payload = JournalEntryWrite(
        entry_date=date(2026, 7, 15),
        summary="Rent receipt",
        lines=[
            JournalLineIn(account_id=cash_id, party_id=party_id, amount=Decimal("1500.00")),
            JournalLineIn(
                account_id=ar_id,
                party_id=party_id,
                amount=Decimal("-1500.00"),
                obligation_id=obligation_id,
            ),
        ],
    )
    csv_bytes = b"settle-rent.csv"
    batch_id, created = ledger_service.create_import_batch_with_entries(
        basename="settle-rent.csv",
        content_sha256=hashlib.sha256(csv_bytes).digest(),
        payloads=[payload],
        confirm_duplicate_content=False,
    )
    assert batch_id > 0
    assert len(created) == 1
    settlement_entry_id = created[0].id
    assert settlement_entry_id != accrual_entry_id

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT accrual_plan_id, import_batch_id FROM journal_entries WHERE id = %s",
                (settlement_entry_id,),
            )
            row = cur.fetchone()
    assert row["accrual_plan_id"] is None
    assert row["import_batch_id"] == batch_id

    ids = _list_entry_ids(api_client, accrual_plan_ids=[plan_id])
    assert sorted(ids) == sorted([accrual_entry_id, settlement_entry_id])
