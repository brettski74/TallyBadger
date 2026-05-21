"""Integration tests for PATCH /accrual-plans/{id} edit with preview regenerate (#171)."""

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
        PartyCreate(name="Tenant Edit", role="customer", is_active=True)
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id),
    )
    return {"cash_id": cash.id, "ar_id": ar.id, "rent_id": rent.id, "party_id": party.id}


def _plan_payload(
    ids: dict[str, int],
    *,
    name: str = "Original Plan",
    amount: str = "100.00",
    end_date: str = "2026-02-28",
) -> dict[str, object]:
    return {
        "name": name,
        "direction": "revenue",
        "party_id": ids["party_id"],
        "target_account_id": ids["rent_id"],
        "bridge_account_id": ids["ar_id"],
        "frequency": "monthly_day",
        "start_date": "2026-01-01",
        "end_date": end_date,
        "amount": amount,
        "summary_template": "{plan} {month}",
        "day_of_month": 1,
        "business_day_adjust": False,
    }


def _count_rows(db_url: str, table: str, *, plan_id: int) -> int:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            if table == "journal_entries":
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


def _obligation_amounts(db_url: str, plan_id: int) -> list[Decimal]:
    with connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT original_amount
                FROM accrual_obligations
                WHERE accrual_plan_id = %s
                ORDER BY id
                """,
                (plan_id,),
            )
            return [Decimal(str(row[0])) for row in cur.fetchall()]


def test_update_accrual_plan_not_found(api_client: TestClient) -> None:
    response = api_client.patch(
        "/accrual-plans/99999",
        json=_plan_payload({"party_id": 1, "rent_id": 2, "ar_id": 3}),
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_update_unsettled_accrual_plan_regenerates_schedule(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    ids = _seed_chart(ledger_service)
    create_response = api_client.post("/accrual-plans", json=_plan_payload(ids))
    assert create_response.status_code == 201
    plan_id = create_response.json()["id"]
    assert _count_rows(integration_db_url, "journal_entries", plan_id=plan_id) == 2
    assert _obligation_amounts(integration_db_url, plan_id) == [
        Decimal("100.00"),
        Decimal("100.00"),
    ]

    updated_payload = _plan_payload(
        ids,
        name="Revised Plan",
        amount="250.00",
        end_date="2026-03-31",
    )
    preview = api_client.post("/accrual-plans/preview", json=updated_payload)
    assert preview.status_code == 200
    assert len(preview.json()) == 3

    response = api_client.patch(f"/accrual-plans/{plan_id}", json=updated_payload)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Revised Plan"
    assert body["amount"] == "250.00"
    assert body["end_date"] == "2026-03-31"

    assert _count_rows(integration_db_url, "journal_entries", plan_id=plan_id) == 3
    assert _obligation_amounts(integration_db_url, plan_id) == [
        Decimal("250.00"),
        Decimal("250.00"),
        Decimal("250.00"),
    ]

    detail = api_client.get(f"/accrual-plans/{plan_id}")
    assert detail.status_code == 200
    assert detail.json()["plan"]["name"] == "Revised Plan"
    assert Decimal(detail.json()["summary"]["total_original_accrued"]) == Decimal("750.00")


def test_update_accrual_plan_allows_past_dated_entries_without_allocations(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """Calendar date must not block edit; only settlement allocations do (#171)."""
    ids = _seed_chart(ledger_service)
    past_start = (date.today() - timedelta(days=90)).replace(day=1)
    past_end = past_start.replace(day=28)
    payload = _plan_payload(
        ids,
        name="Past Dated Plan",
        amount="50.00",
        end_date=past_end.isoformat(),
    )
    payload["start_date"] = past_start.isoformat()

    create_response = api_client.post("/accrual-plans", json=payload)
    assert create_response.status_code == 201
    plan_id = create_response.json()["id"]

    updated = dict(payload)
    updated["name"] = "Past Dated Revised"
    updated["amount"] = "75.00"
    response = api_client.patch(f"/accrual-plans/{plan_id}", json=updated)
    assert response.status_code == 200
    assert response.json()["name"] == "Past Dated Revised"
    assert _obligation_amounts(integration_db_url, plan_id) == [Decimal("75.00")]


def test_update_accrual_plan_rejects_when_allocations_exist(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    ids = _seed_chart(ledger_service)
    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Settled For Edit",
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

    updated_payload = _plan_payload(ids, name="Should Not Apply", amount="200.00")
    response = api_client.patch(f"/accrual-plans/{plan.id}", json=updated_payload)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Settled For Edit" in detail
    assert f"id={plan.id}" in detail
    assert "settlement allocation" in detail.lower()
    assert "obligation" in detail.lower()

    assert _count_rows(integration_db_url, "journal_entries", plan_id=plan.id) == 1
    assert _obligation_amounts(integration_db_url, plan.id) == [Decimal("100.00")]

    refreshed = ledger_service.get_accrual_plan_detail(plan.id)
    assert refreshed.plan.name == "Settled For Edit"
    assert refreshed.plan.amount == Decimal("100.00")
