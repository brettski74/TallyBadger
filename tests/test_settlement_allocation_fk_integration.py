"""Integration tests: journal line ↔ settlement allocation FK (#270)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.backup.snapshot import export_complete_snapshot, import_complete_snapshot
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.import_rules.cel_rule_set_service import CelRuleSetService
from tallybadger.ledger.models import (
    AccountCreate,
    AccrualPlanCreate,
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
def api_client(integration_db_url: str) -> Iterator[TestClient]:
    from tallybadger.api.routes.ledger import get_ledger_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    def _ledger() -> LedgerService:
        return LedgerService(connection_factory=connection_factory)

    app.dependency_overrides[get_ledger_service] = _ledger
    yield TestClient(app)
    app.dependency_overrides.pop(get_ledger_service, None)


@pytest.fixture
def ledger_service(integration_db_url: str) -> LedgerService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return LedgerService(connection_factory=connection_factory)


def _seed_chart(ledger_service: LedgerService) -> dict[str, int]:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(
        AccountCreate(name="Accounts Receivable", type="asset")
    )
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    party = ledger_service.create_party(
        PartyCreate(name="Pamela Tenant", role="customer", is_active=True)
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id)
    )
    return {
        "cash_id": cash.id,
        "ar_id": ar.id,
        "rent_id": rent.id,
        "party_id": party.id,
    }


def _rent_obligation(ledger_service: LedgerService, ids: dict[str, int], *, name: str) -> int:
    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name=name,
            direction="revenue",
            party_id=ids["party_id"],
            target_account_id=ids["rent_id"],
            frequency="monthly_day",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
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
    return obligations[0].id


def test_get_manual_settlement_links_allocation_and_obligation_on_bridge_line(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    ids = _seed_chart(ledger_service)
    obligation_id = _rent_obligation(ledger_service, ids, name="July rent")

    create = api_client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-07-15",
            "summary": "Rent receipt",
            "lines": [
                {"account_id": ids["cash_id"], "party_id": ids["party_id"], "amount": "500.00"},
                {
                    "account_id": ids["ar_id"],
                    "party_id": ids["party_id"],
                    "amount": "-500.00",
                    "obligation_id": obligation_id,
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    entry_id = create.json()["id"]

    entry = api_client.get(f"/journal-entries/{entry_id}").json()
    assert len(entry["settlement_allocations"]) == 1
    alloc = entry["settlement_allocations"][0]
    assert alloc["obligation_id"] == obligation_id
    assert Decimal(alloc["amount"]) == Decimal("500.00")

    bridge_lines = [line for line in entry["lines"] if line["account_id"] == ids["ar_id"]]
    assert len(bridge_lines) == 1
    bridge = bridge_lines[0]
    assert bridge["settlement_allocation_id"] == alloc["id"]
    assert bridge["obligation_id"] == obligation_id
    assert bridge["obligation_source_entry_summary"] == "July rent"
    assert bridge["obligation_target_account_id"] == ids["rent_id"]


def test_get_same_day_collapse_links_allocation_to_source_bridge_line(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    ids = _seed_chart(ledger_service)
    obligation_id = _rent_obligation(ledger_service, ids, name="July rent")

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_line_id, source_entry_id FROM accrual_obligations WHERE id = %s",
                (obligation_id,),
            )
            row = cur.fetchone()
            source_line_id = int(row["source_line_id"])
            accrual_entry_id = int(row["source_entry_id"])

    create = api_client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-07-01",
            "summary": "Same-day rent",
            "lines": [
                {"account_id": ids["cash_id"], "party_id": ids["party_id"], "amount": "500.00"},
                {
                    "account_id": ids["ar_id"],
                    "party_id": ids["party_id"],
                    "amount": "-500.00",
                    "obligation_id": obligation_id,
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    assert create.json()["id"] == accrual_entry_id

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert len(entry["settlement_allocations"]) == 1
    alloc = entry["settlement_allocations"][0]
    assert alloc["obligation_id"] == obligation_id

    linked = next(
        line for line in entry["lines"] if line["settlement_allocation_id"] == alloc["id"]
    )
    assert linked["id"] == source_line_id
    assert linked["obligation_id"] == obligation_id
    assert entry["accrual_plan_id"] is not None
    assert entry["accrual_plan_name"] == "July rent"


def test_settlements_tab_uses_per_obligation_bridge_lines_with_fk(
    ledger_service: LedgerService,
) -> None:
    ids = _seed_chart(ledger_service)
    ob_a = _rent_obligation(ledger_service, ids, name="July A")
    ob_b = _rent_obligation(ledger_service, ids, name="August B")

    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=ids["party_id"],
            settlement_type="receipt",
            event_date=date(2026, 8, 15),
            amount=Decimal("700.00"),
            cash_account_id=ids["cash_id"],
            allocations=[
                SettlementAllocationIn(obligation_id=ob_a, amount=Decimal("300.00")),
                SettlementAllocationIn(obligation_id=ob_b, amount=Decimal("400.00")),
            ],
        )
    )

    entry = ledger_service.get_entry(result.entry_id)
    assert len(entry.settlement_allocations) == 2
    bridge_lines = [line for line in entry.lines if line.account_id == ids["ar_id"]]
    assert len(bridge_lines) == 2
    assert {Decimal(line.amount) for line in bridge_lines} == {
        Decimal("-300.00"),
        Decimal("-400.00"),
    }
    for alloc in entry.settlement_allocations:
        linked = next(
            line for line in entry.lines if line.settlement_allocation_id == alloc.id
        )
        assert linked.obligation_id == alloc.obligation_id
        assert abs(linked.amount) == alloc.amount


def test_manual_multi_obligation_create_round_trips_on_get(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    ids = _seed_chart(ledger_service)
    ob_a = _rent_obligation(ledger_service, ids, name="Plan A")
    ob_b = _rent_obligation(ledger_service, ids, name="Plan B")

    create = api_client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-08-20",
            "summary": "Two rent receipts",
            "lines": [
                {"account_id": ids["cash_id"], "party_id": ids["party_id"], "amount": "900.00"},
                {
                    "account_id": ids["ar_id"],
                    "party_id": ids["party_id"],
                    "amount": "-500.00",
                    "obligation_id": ob_a,
                },
                {
                    "account_id": ids["ar_id"],
                    "party_id": ids["party_id"],
                    "amount": "-400.00",
                    "obligation_id": ob_b,
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    entry = api_client.get(f"/journal-entries/{create.json()['id']}").json()
    assert len(entry["settlement_allocations"]) == 2
    by_obligation = {alloc["obligation_id"]: alloc for alloc in entry["settlement_allocations"]}
    assert set(by_obligation) == {ob_a, ob_b}
    for line in entry["lines"]:
        if line["obligation_id"] is None:
            continue
        alloc = by_obligation[line["obligation_id"]]
        assert line["settlement_allocation_id"] == alloc["id"]


def test_snapshot_export_import_preserves_settlement_allocation_fk(
    integration_db_url: str,
    ledger_service: LedgerService,
) -> None:
    ids = _seed_chart(ledger_service)
    obligation_id = _rent_obligation(ledger_service, ids, name="Snapshot rent")
    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=ids["party_id"],
            settlement_type="receipt",
            event_date=date(2026, 9, 1),
            amount=Decimal("500.00"),
            cash_account_id=ids["cash_id"],
            allocations=[
                SettlementAllocationIn(obligation_id=obligation_id, amount=Decimal("500.00")),
            ],
        )
    )
    before = ledger_service.get_entry(result.entry_id)

    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_complete_snapshot(conn)

    with connect(integration_db_url, row_factory=dict_row) as conn:
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
        import_complete_snapshot(conn, archive, restore_mode="erase-reload")

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    restored = LedgerService(connection_factory=connection_factory).get_entry(before.id)
    assert len(restored.settlement_allocations) == 1
    alloc = restored.settlement_allocations[0]
    linked = next(
        line for line in restored.lines if line.settlement_allocation_id == alloc.id
    )
    assert linked.obligation_id == alloc.obligation_id
