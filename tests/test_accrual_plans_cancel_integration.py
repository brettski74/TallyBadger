"""Integration tests for DELETE /accrual-plans/{id} cancel unsettled plan (#170)."""

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
                      settlement_allocations,
                      journal_lines, journal_entry_attachments,
                      attachments, journal_entries, import_batches,
                      accrual_obligations, accrual_plans, party_match_patterns,
                      parties, accounts, cel_rule_sets
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
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    party = ledger_service.create_party(
        PartyCreate(name="Tenant Cancel", role="customer", is_active=True)
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id),
    )
    return {"cash_id": cash.id, "ar_id": ar.id, "rent_id": rent.id, "party_id": party.id}


def _count_rows(db_url: str, table: str, *, plan_id: int | None = None) -> int:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            if plan_id is None:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
            elif table == "accrual_plans":
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE id = %s", (plan_id,))
            elif table == "journal_entries":
                cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE accrual_plan_id = %s",
                    (plan_id,),
                )
            elif table == "accrual_obligations":
                cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE accrual_plan_id = %s",
                    (plan_id,),
                )
            else:
                raise ValueError(table)
            return int(cur.fetchone()[0])


def test_cancel_accrual_plan_not_found(api_client: TestClient) -> None:
    response = api_client.delete("/accrual-plans/99999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_cancel_unsettled_accrual_plan_removes_plan_jes_and_obligations(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    ids = _seed_chart(ledger_service)
    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Cancel Me",
            direction="revenue",
            party_id=ids["party_id"],
            target_account_id=ids["rent_id"],
            bridge_account_id=ids["ar_id"],
            frequency="monthly_day",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 28),
            amount=Decimal("200.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )
    assert _count_rows(integration_db_url, "accrual_plans", plan_id=plan.id) == 1
    assert _count_rows(integration_db_url, "journal_entries", plan_id=plan.id) == 2
    assert _count_rows(integration_db_url, "accrual_obligations", plan_id=plan.id) == 2

    response = api_client.delete(f"/accrual-plans/{plan.id}")
    assert response.status_code == 204

    assert _count_rows(integration_db_url, "accrual_plans", plan_id=plan.id) == 0
    assert _count_rows(integration_db_url, "journal_entries", plan_id=plan.id) == 0
    assert _count_rows(integration_db_url, "accrual_obligations", plan_id=plan.id) == 0
    assert _count_rows(integration_db_url, "settlement_allocations") == 0

    list_response = api_client.get("/accrual-plans")
    assert list_response.status_code == 200
    assert list_response.json()["plans"] == []


def test_cancel_accrual_plan_rejects_when_allocations_exist(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    ids = _seed_chart(ledger_service)
    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Settled Partial",
            direction="revenue",
            party_id=ids["party_id"],
            target_account_id=ids["rent_id"],
            bridge_account_id=ids["ar_id"],
            frequency="monthly_day",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            amount=Decimal("100.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )
    obligation = next(
        ob
        for ob in ledger_service.list_open_obligations(ids["party_id"])
        if ob.accrual_plan_id == plan.id
    )
    ledger_service.record_settlement(
        SettlementWrite(
            party_id=ids["party_id"],
            settlement_type="receipt",
            event_date=date(2026, 1, 15),
            amount=Decimal("25.00"),
            cash_account_id=ids["cash_id"],
            allocations=[
                SettlementAllocationIn(obligation_id=obligation.id, amount=Decimal("25.00")),
            ],
        )
    )
    assert _count_rows(integration_db_url, "settlement_allocations") == 1

    response = api_client.delete(f"/accrual-plans/{plan.id}")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "settlement allocations" in detail.lower()
    assert "Settled Partial" in detail

    assert _count_rows(integration_db_url, "accrual_plans", plan_id=plan.id) == 1
    assert _count_rows(integration_db_url, "journal_entries", plan_id=plan.id) == 1
    assert _count_rows(integration_db_url, "accrual_obligations", plan_id=plan.id) == 1
    assert _count_rows(integration_db_url, "settlement_allocations") == 1
