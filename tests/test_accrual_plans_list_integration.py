"""Integration tests for filtered GET /accrual-plans (#168)."""

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


def _seed_filter_fixtures(ledger_service: LedgerService) -> dict[str, int]:
    """Three plans: unsettled/open, partially settled, fully settled."""
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    party_a = ledger_service.create_party(
        PartyCreate(name="Tenant Alpha", role="customer", is_active=True)
    )
    party_b = ledger_service.create_party(
        PartyCreate(name="Tenant Beta", role="customer", is_active=True)
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id),
    )

    unsettled = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Alpha Rent Plan",
            direction="revenue",
            party_id=party_a.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            amount=Decimal("1000.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    partial = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Beta Two Month",
            direction="revenue",
            party_id=party_b.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 3, 31),
            amount=Decimal("500.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )
    beta_obs = ledger_service.list_open_obligations(party_b.id)
    assert len(beta_obs) == 2
    ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_b.id,
            settlement_type="receipt",
            event_date=date(2026, 2, 1),
            amount=Decimal("500.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=beta_obs[0].id, amount=Decimal("500.00")),
            ],
        )
    )

    settled = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Closed Plan",
            direction="revenue",
            party_id=party_a.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 30),
            amount=Decimal("800.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )
    closed_obs = ledger_service.list_open_obligations(party_a.id)
    closed_ob = next(ob for ob in closed_obs if ob.accrual_plan_id == settled.id)
    ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_a.id,
            settlement_type="receipt",
            event_date=date(2025, 6, 1),
            amount=Decimal("800.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=closed_ob.id, amount=Decimal("800.00")),
            ],
        )
    )

    return {
        "unsettled_id": unsettled.id,
        "partial_id": partial.id,
        "settled_id": settled.id,
        "party_a_id": party_a.id,
        "party_b_id": party_b.id,
        "rent_id": rent.id,
        "ar_id": ar.id,
    }


def _plan_ids(response) -> list[int]:
    return [p["id"] for p in response.json()["plans"]]


def test_list_accrual_plans_no_filter_returns_all(api_client: TestClient, ledger_service: LedgerService) -> None:
    ids = _seed_filter_fixtures(ledger_service)
    response = api_client.get("/accrual-plans")
    assert response.status_code == 200
    assert set(_plan_ids(response)) == {
        ids["unsettled_id"],
        ids["partial_id"],
        ids["settled_id"],
    }
    assert response.json()["filter_options"] is None


def test_list_accrual_plans_has_settlement_allocations_flag(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    ids = _seed_filter_fixtures(ledger_service)
    response = api_client.get("/accrual-plans")
    by_id = {p["id"]: p for p in response.json()["plans"]}
    assert by_id[ids["unsettled_id"]]["has_settlement_allocations"] is False
    assert by_id[ids["partial_id"]]["has_settlement_allocations"] is True
    assert by_id[ids["settled_id"]]["has_settlement_allocations"] is True


@pytest.mark.parametrize(
    ("status", "expected_key"),
    [
        ("unsettled", "unsettled_id"),
        ("open", "unsettled_id"),
        ("partially_settled", "partial_id"),
        ("settled", "settled_id"),
    ],
)
def test_list_accrual_plans_settlement_status_buckets(
    api_client: TestClient,
    ledger_service: LedgerService,
    status: str,
    expected_key: str,
) -> None:
    ids = _seed_filter_fixtures(ledger_service)
    response = api_client.get("/accrual-plans", params={"settlement_status": status})
    assert response.status_code == 200
    result_ids = _plan_ids(response)
    assert ids[expected_key] in result_ids
    if status == "open":
        assert ids["partial_id"] in result_ids
        assert ids["settled_id"] not in result_ids
    elif status == "unsettled":
        assert len(result_ids) == 1
    elif status == "partially_settled":
        assert len(result_ids) == 1
    elif status == "settled":
        assert len(result_ids) == 1


def test_list_accrual_plans_open_includes_partial_not_settled(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    ids = _seed_filter_fixtures(ledger_service)
    response = api_client.get("/accrual-plans", params={"settlement_status": "open"})
    assert set(_plan_ids(response)) == {ids["unsettled_id"], ids["partial_id"]}


def test_list_accrual_plans_party_and_date_filters(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    ids = _seed_filter_fixtures(ledger_service)
    by_party = api_client.get("/accrual-plans", params={"party_ids": [ids["party_b_id"]]})
    assert _plan_ids(by_party) == [ids["partial_id"]]

    by_date = api_client.get(
        "/accrual-plans",
        params={"from_date": "2026-02-01", "to_date": "2026-02-28"},
    )
    assert set(_plan_ids(by_date)) == {ids["partial_id"]}


def test_list_accrual_plans_name_regex_case_insensitive(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    ids = _seed_filter_fixtures(ledger_service)
    response = api_client.get("/accrual-plans", params={"name": "alpha"})
    assert _plan_ids(response) == [ids["unsettled_id"]]


def test_list_accrual_plans_combined_filters_and_semantics(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    ids = _seed_filter_fixtures(ledger_service)
    response = api_client.get(
        "/accrual-plans",
        params={
            "party_ids": [ids["party_a_id"]],
            "settlement_status": "open",
            "from_date": "2026-01-01",
            "to_date": "2026-12-31",
        },
    )
    assert _plan_ids(response) == [ids["unsettled_id"]]


def test_list_accrual_plans_invalid_name_regex_returns_422(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    _seed_filter_fixtures(ledger_service)
    response = api_client.get("/accrual-plans", params={"name": "["})
    assert response.status_code == 422


def test_list_accrual_plans_include_filter_options(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    ids = _seed_filter_fixtures(ledger_service)
    response = api_client.get(
        "/accrual-plans",
        params={"party_ids": [ids["party_a_id"]], "include_filter_options": True},
    )
    assert response.status_code == 200
    assert set(_plan_ids(response)) == {ids["unsettled_id"], ids["settled_id"]}
    opts = response.json()["filter_options"]
    assert set(opts["party_ids"]) == {ids["party_a_id"], ids["party_b_id"]}
    assert opts["target_account_ids"] == [ids["rent_id"]]
    assert opts["bridge_account_ids"] == [ids["ar_id"]]
