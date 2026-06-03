"""Integration tests for inferred accrual plan bridge from ledger settings (#235)."""

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


def _seed_revenue_chart(ledger_service: LedgerService) -> dict[str, int]:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    party = ledger_service.create_party(
        PartyCreate(name="Tenant Bridge", role="customer", is_active=True)
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id),
    )
    return {"cash_id": cash.id, "ar_id": ar.id, "rent_id": rent.id, "party_id": party.id}


def test_create_accrual_plan_posts_to_ledger_ar_and_settles(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    ids = _seed_revenue_chart(ledger_service)
    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Inferred AR Plan",
            direction="revenue",
            party_id=ids["party_id"],
            target_account_id=ids["rent_id"],
            frequency="monthly_day",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            amount=Decimal("500.00"),
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
    obligation = obligations[0]

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT jl.account_id
                FROM journal_lines jl
                WHERE jl.id = %s
                """,
                (obligation.source_line_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert int(row["account_id"]) == ids["ar_id"]

    ledger_service.record_settlement(
        SettlementWrite(
            party_id=ids["party_id"],
            settlement_type="receipt",
            event_date=date(2026, 6, 15),
            cash_account_id=ids["cash_id"],
            amount=Decimal("500.00"),
            allocations=[SettlementAllocationIn(obligation_id=obligation.id, amount=Decimal("500.00"))],
        )
    )
    refreshed = ledger_service.list_open_obligations(ids["party_id"])
    assert all(ob.open_amount == Decimal("0") for ob in refreshed if ob.id == obligation.id)


def test_create_accrual_plan_without_ar_returns_422(api_client: TestClient) -> None:
    response = api_client.post(
        "/accrual-plans",
        json={
            "name": "No AR",
            "direction": "revenue",
            "party_id": 1,
            "target_account_id": 1,
            "frequency": "monthly_day",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "amount": "100.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert response.status_code == 422
    assert "accounts receivable" in response.json()["detail"].lower()
