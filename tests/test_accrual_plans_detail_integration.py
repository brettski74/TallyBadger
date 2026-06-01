"""Integration tests for GET /accrual-plans/{id} with summary rollups (#169).

Rollup SQL compares obligation ``source_entry_date`` to PostgreSQL ``CURRENT_DATE``.
Application connections configure PostgreSQL ``TIME ZONE`` to match the host calendar
(see :mod:`tallybadger.core.timezone`).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
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
    AccrualPlanCreate,
    LedgerSettingsUpdate,
    PartyCreate,
    SettlementAllocationIn,
    SettlementWrite,
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


def _seed_chart(ledger_service: LedgerService) -> dict[str, int]:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    ur = ledger_service.create_account(AccountCreate(name="Unearned Revenue", type="liability"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    party = ledger_service.create_party(
        PartyCreate(name="Tenant Rollup", role="customer", is_active=True)
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_receivable_account_id=ar.id,
            unearned_revenue_account_id=ur.id,
        ),
    )
    return {"cash_id": cash.id, "ar_id": ar.id, "rent_id": rent.id, "party_id": party.id}


def _seed_expense_chart(ledger_service: LedgerService) -> dict[str, int]:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ap = ledger_service.create_account(AccountCreate(name="Accounts Payable", type="liability"))
    prepaid = ledger_service.create_account(AccountCreate(name="Prepaid Expenses", type="asset"))
    repairs = ledger_service.create_account(AccountCreate(name="Repairs Expense", type="expense"))
    party = ledger_service.create_party(
        PartyCreate(name="Vendor Rollup", role="vendor", is_active=True)
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_payable_account_id=ap.id,
            prepaid_expenses_account_id=prepaid.id,
        ),
    )
    return {
        "cash_id": cash.id,
        "ap_id": ap.id,
        "prepaid_id": prepaid.id,
        "expense_id": repairs.id,
        "party_id": party.id,
    }


def _set_obligation_entry_dates(
    integration_db_url: str,
    *,
    obligation_dates: dict[int, date],
) -> None:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for obligation_id, entry_date in obligation_dates.items():
                    cur.execute(
                        """
                        UPDATE journal_entries je
                        SET entry_date = %s
                        FROM accrual_obligations ao
                        WHERE ao.id = %s
                          AND je.id = ao.source_entry_id
                        """,
                        (entry_date, obligation_id),
                    )


def test_get_accrual_plan_detail_not_found(api_client: TestClient) -> None:
    response = api_client.get("/accrual-plans/99999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_accrual_plan_detail_rollups_and_today_boundary(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """Past / not-yet / unearned use strict date comparisons; today only in obligations."""
    ids = _seed_chart(ledger_service)
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Rollup Three Month",
            direction="revenue",
            party_id=ids["party_id"],
            target_account_id=ids["rent_id"],
            bridge_account_id=ids["ar_id"],
            frequency="monthly_day",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            amount=Decimal("300.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )
    obligations = [
        ob
        for ob in ledger_service.list_open_obligations(ids["party_id"])
        if ob.accrual_plan_id == plan.id
    ]
    assert len(obligations) == 3
    obligations.sort(key=lambda ob: ob.id)
    past_ob, today_ob, future_ob = obligations

    _set_obligation_entry_dates(
        integration_db_url,
        obligation_dates={
            past_ob.id: yesterday,
            today_ob.id: today,
            future_ob.id: tomorrow,
        },
    )

    ledger_service.record_settlement(
        SettlementWrite(
            party_id=ids["party_id"],
            settlement_type="receipt",
            event_date=today,
            amount=Decimal("50.00"),
            cash_account_id=ids["cash_id"],
            allocations=[
                SettlementAllocationIn(obligation_id=today_ob.id, amount=Decimal("50.00")),
            ],
        )
    )
    ledger_service.record_settlement(
        SettlementWrite(
            party_id=ids["party_id"],
            settlement_type="receipt",
            event_date=today,
            amount=Decimal("100.00"),
            cash_account_id=ids["cash_id"],
            allocations=[
                SettlementAllocationIn(obligation_id=future_ob.id, amount=Decimal("100.00")),
            ],
        )
    )

    response = api_client.get(f"/accrual-plans/{plan.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["id"] == plan.id
    assert len(body["obligations"]) == 3

    summary = body["summary"]
    assert Decimal(summary["total_original_accrued"]) == Decimal("900.00")
    assert Decimal(summary["total_settled_to_date"]) == Decimal("150.00")
    assert Decimal(summary["past_due"]) == Decimal("300.00")
    assert Decimal(summary["not_yet_due"]) == Decimal("200.00")
    assert Decimal(summary["unearned"]) == Decimal("100.00")
    assert Decimal(summary["prepaid"]) == Decimal("100.00")

    open_on_today = Decimal("250.00")
    total_open = sum(Decimal(ob["open_amount"]) for ob in body["obligations"])
    assert total_open == Decimal("750.00")
    assert (
        Decimal(summary["past_due"])
        + Decimal(summary["not_yet_due"])
        + open_on_today
        == total_open
    )

    by_id = {ob["id"]: ob for ob in body["obligations"]}
    assert by_id[today_ob.id]["source_entry_date"] == today.isoformat()
    assert Decimal(by_id[today_ob.id]["open_amount"]) == open_on_today


def test_get_accrual_plan_detail_today_excluded_from_date_bucket_rollups(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """Obligation on CURRENT_DATE contributes zero to past_due, not_yet_due, and unearned."""
    ids = _seed_chart(ledger_service)
    today = date.today()

    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Today Only",
            direction="revenue",
            party_id=ids["party_id"],
            target_account_id=ids["rent_id"],
            bridge_account_id=ids["ar_id"],
            frequency="monthly_day",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            amount=Decimal("400.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )
    obligations = [
        ob
        for ob in ledger_service.list_open_obligations(ids["party_id"])
        if ob.accrual_plan_id == plan.id
    ]
    assert len(obligations) == 1
    today_ob = obligations[0]
    _set_obligation_entry_dates(
        integration_db_url,
        obligation_dates={today_ob.id: today},
    )

    response = api_client.get(f"/accrual-plans/{plan.id}")
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert Decimal(summary["past_due"]) == Decimal("0")
    assert Decimal(summary["not_yet_due"]) == Decimal("0")
    assert Decimal(summary["unearned"]) == Decimal("0")
    assert Decimal(summary["prepaid"]) == Decimal("0")
    assert Decimal(summary["total_original_accrued"]) == Decimal("400.00")
    assert Decimal(summary["total_settled_to_date"]) == Decimal("0")


def test_get_accrual_plan_detail_expense_prepaid_rollup(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """Expense plan prepaid rollup mirrors revenue unearned (settled on future obligations)."""
    ids = _seed_expense_chart(ledger_service)
    today = date.today()
    tomorrow = today + timedelta(days=1)

    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Expense Rollup",
            direction="expense",
            party_id=ids["party_id"],
            target_account_id=ids["expense_id"],
            bridge_account_id=ids["ap_id"],
            frequency="monthly_day",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 28),
            amount=Decimal("200.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )
    obligations = [
        ob
        for ob in ledger_service.list_open_obligations(ids["party_id"])
        if ob.accrual_plan_id == plan.id
    ]
    assert len(obligations) == 2
    obligations.sort(key=lambda ob: ob.id)
    future_ob = obligations[-1]

    _set_obligation_entry_dates(
        integration_db_url,
        obligation_dates={future_ob.id: tomorrow},
    )

    ledger_service.record_settlement(
        SettlementWrite(
            party_id=ids["party_id"],
            settlement_type="payment",
            event_date=today,
            amount=Decimal("75.00"),
            cash_account_id=ids["cash_id"],
            allocations=[
                SettlementAllocationIn(obligation_id=future_ob.id, amount=Decimal("75.00")),
            ],
        )
    )

    response = api_client.get(f"/accrual-plans/{plan.id}")
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert Decimal(summary["prepaid"]) == Decimal("75.00")
    assert Decimal(summary["unearned"]) == Decimal("75.00")
