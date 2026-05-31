"""Integration tests: manual journal create with obligation settlement on lines (#220)."""

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

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.import_rules.cel_rule_set_service import CelRuleSetService
from tallybadger.ledger.models import JournalEntryWrite, JournalLineIn
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
    from tallybadger.api.routes.cel_rule_sets import get_cel_rule_set_service
    from tallybadger.api.routes.ledger import get_ledger_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    def _ledger() -> LedgerService:
        return LedgerService(connection_factory=connection_factory)

    app.dependency_overrides[get_ledger_service] = _ledger
    app.dependency_overrides[get_cel_rule_set_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_ledger_service, None)
    app.dependency_overrides.pop(get_cel_rule_set_service, None)


def _count_rows(integration_db_url: str, table: str) -> int:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
            return int(cur.fetchone()["c"])


def _setup_rent_accrual(api_client: TestClient) -> tuple[int, int, int, int, int]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201

    accounts = api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    cash_id = by_name["Cash"]
    ar_id = by_name["Accounts Receivable"]
    rent_id = by_name["Rent Revenue"]

    pr = api_client.post(
        "/parties",
        json={"name": "Pamela Tenant", "role": "customer", "is_active": True},
    )
    assert pr.status_code == 201, pr.text
    party_id = pr.json()["id"]

    assert (
        api_client.patch(
            "/ledger-settings",
            json={"accounts_receivable_account_id": ar_id},
        ).status_code
        == 200
    )

    plan = api_client.post(
        "/accrual-plans",
        json={
            "name": "July rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": rent_id,
            "bridge_account_id": ar_id,
            "frequency": "monthly_day",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "amount": "1500.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    obligation_id = obligations[0]["id"]
    accrual_entry_id = obligations[0]["source_entry_id"]
    return party_id, cash_id, ar_id, obligation_id, accrual_entry_id


def _manual_settlement_payload(
    *,
    entry_date: date,
    cash_id: int,
    ar_id: int,
    party_id: int,
    obligation_id: int,
    amount: Decimal,
    summary: str = "Rent receipt",
) -> dict:
    return {
        "entry_date": entry_date.isoformat(),
        "summary": summary,
        "lines": [
            {"account_id": cash_id, "party_id": party_id, "amount": str(amount)},
            {
                "account_id": ar_id,
                "party_id": party_id,
                "amount": str(-amount),
                "obligation_id": obligation_id,
            },
        ],
    }


def _setup_rent_accrual_with_unearned(api_client: TestClient) -> tuple[int, int, int, int, int, int]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
        {"name": "Unearned Revenue", "type": "liability", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201

    accounts = api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    cash_id = by_name["Cash"]
    ar_id = by_name["Accounts Receivable"]
    rent_id = by_name["Rent Revenue"]
    ur_id = by_name["Unearned Revenue"]

    pr = api_client.post(
        "/parties",
        json={"name": "Early Payer", "role": "customer", "is_active": True},
    )
    assert pr.status_code == 201, pr.text
    party_id = pr.json()["id"]

    assert (
        api_client.patch(
            "/ledger-settings",
            json={
                "accounts_receivable_account_id": ar_id,
                "unearned_revenue_account_id": ur_id,
            },
        ).status_code
        == 200
    )

    plan = api_client.post(
        "/accrual-plans",
        json={
            "name": "July rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": rent_id,
            "bridge_account_id": ar_id,
            "frequency": "monthly_day",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "amount": "1500.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    obligation_id = obligations[0]["id"]
    accrual_entry_id = obligations[0]["source_entry_id"]
    return party_id, cash_id, ar_id, ur_id, obligation_id, accrual_entry_id


def test_manual_create_early_receipt_uses_unearned_settlement_line(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, ur_id, obligation_id, accrual_entry_id = _setup_rent_accrual_with_unearned(
        api_client
    )

    r = api_client.post(
        "/journal-entries",
        json={
            "entry_date": date(2026, 6, 26).isoformat(),
            "summary": "Early June rent",
            "lines": [
                {"account_id": cash_id, "party_id": party_id, "amount": "1500.00"},
                {
                    "account_id": ur_id,
                    "party_id": party_id,
                    "amount": "-1500.00",
                    "obligation_id": obligation_id,
                },
            ],
        },
    )
    assert r.status_code == 201, r.text
    receipt_entry_id = r.json()["id"]
    assert receipt_entry_id != accrual_entry_id

    receipt = api_client.get(f"/journal-entries/{receipt_entry_id}").json()
    bridge_lines = [line for line in receipt["lines"] if line["account_id"] == ur_id]
    assert len(bridge_lines) == 1
    assert Decimal(bridge_lines[0]["amount"]) == Decimal("-1500.00")

    accrual = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    accrual_account_ids = {line["account_id"] for line in accrual["lines"]}
    assert ar_id not in accrual_account_ids
    assert ur_id in accrual_account_ids


def test_manual_create_settlement_single_obligation(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _ = _setup_rent_accrual(api_client)

    r = api_client.post(
        "/journal-entries",
        json=_manual_settlement_payload(
            entry_date=date(2026, 7, 15),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("1500.00"),
        ),
    )
    assert r.status_code == 201, r.text
    assert _count_rows(integration_db_url, "settlement_allocations") == 1
    assert _count_rows(integration_db_url, "journal_entries") == 2
    assert _count_rows(integration_db_url, "import_batches") == 0

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert obligations == []


def test_manual_create_settlement_partial_leaves_obligation_open(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _ = _setup_rent_accrual(api_client)

    r = api_client.post(
        "/journal-entries",
        json=_manual_settlement_payload(
            entry_date=date(2026, 7, 15),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("500.00"),
            summary="Partial rent",
        ),
    )
    assert r.status_code == 201, r.text

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "partially_settled"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("1000.00")


def test_manual_same_day_full_receipt_collapses_into_accrual(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, accrual_entry_id = _setup_rent_accrual(api_client)

    r = api_client.post(
        "/journal-entries",
        json=_manual_settlement_payload(
            entry_date=date(2026, 7, 1),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("1500.00"),
        ),
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == accrual_entry_id
    assert _count_rows(integration_db_url, "journal_entries") == 1

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT import_batch_id FROM journal_entries WHERE id = %s",
                (accrual_entry_id,),
            )
            assert cur.fetchone()["import_batch_id"] is None


def test_manual_non_same_day_creates_separate_journal(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, accrual_entry_id = _setup_rent_accrual(api_client)

    r = api_client.post(
        "/journal-entries",
        json=_manual_settlement_payload(
            entry_date=date(2026, 7, 15),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("1500.00"),
        ),
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] != accrual_entry_id
    assert _count_rows(integration_db_url, "journal_entries") == 2


def test_manual_create_rejects_unknown_obligation_id(
    api_client: TestClient,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _ = _setup_rent_accrual(api_client)

    payload = _manual_settlement_payload(
        entry_date=date(2026, 7, 15),
        cash_id=cash_id,
        ar_id=ar_id,
        party_id=party_id,
        obligation_id=obligation_id,
        amount=Decimal("100.00"),
    )
    payload["lines"][1]["obligation_id"] = 99999

    r = api_client.post("/journal-entries", json=payload)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"].lower()
    assert "obligation" in detail
    assert "99999" in detail


def test_manual_create_rejects_wrong_bridge_account(
    api_client: TestClient,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _ = _setup_rent_accrual(api_client)

    payload = _manual_settlement_payload(
        entry_date=date(2026, 7, 15),
        cash_id=cash_id,
        ar_id=ar_id,
        party_id=party_id,
        obligation_id=obligation_id,
        amount=Decimal("100.00"),
    )
    payload["lines"][1]["account_id"] = cash_id

    r = api_client.post("/journal-entries", json=payload)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"].lower()
    assert "obligation" in detail
    assert "pamela tenant" in detail
    assert "accounts receivable" in detail


def _setup_repair_accrual_with_prepaid(api_client: TestClient) -> tuple[int, int, int, int, int, int, int]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
        {"name": "Prepaid Expenses", "type": "asset", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201

    accounts = api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    cash_id = by_name["Cash"]
    ap_id = by_name["Accounts Payable"]
    expense_id = by_name["Repairs Expense"]
    prepaid_id = by_name["Prepaid Expenses"]

    pr = api_client.post(
        "/parties",
        json={"name": "Early Vendor", "role": "vendor", "is_active": True},
    )
    assert pr.status_code == 201, pr.text
    party_id = pr.json()["id"]

    assert (
        api_client.patch(
            "/ledger-settings",
            json={
                "accounts_payable_account_id": ap_id,
                "prepaid_expenses_account_id": prepaid_id,
            },
        ).status_code
        == 200
    )

    plan = api_client.post(
        "/accrual-plans",
        json={
            "name": "August repair",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": expense_id,
            "bridge_account_id": ap_id,
            "frequency": "monthly_day",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "amount": "800.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    obligation_id = obligations[0]["id"]
    accrual_entry_id = obligations[0]["source_entry_id"]
    return party_id, cash_id, ap_id, prepaid_id, obligation_id, accrual_entry_id, expense_id


def _manual_payment_settlement_payload(
    *,
    entry_date: date,
    cash_id: int,
    bridge_id: int,
    party_id: int,
    obligation_id: int,
    amount: Decimal,
    summary: str = "Vendor payment",
) -> dict:
    return {
        "entry_date": entry_date.isoformat(),
        "summary": summary,
        "lines": [
            {"account_id": cash_id, "party_id": party_id, "amount": str(-amount)},
            {
                "account_id": bridge_id,
                "party_id": party_id,
                "amount": str(amount),
                "obligation_id": obligation_id,
            },
        ],
    }


def test_manual_create_early_payment_uses_prepaid_settlement_line(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ap_id, prepaid_id, obligation_id, accrual_entry_id, _ = (
        _setup_repair_accrual_with_prepaid(api_client)
    )

    r = api_client.post(
        "/journal-entries",
        json=_manual_payment_settlement_payload(
            entry_date=date(2026, 7, 26),
            cash_id=cash_id,
            bridge_id=prepaid_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("800.00"),
        ),
    )
    assert r.status_code == 201, r.text
    payment_entry_id = r.json()["id"]
    assert payment_entry_id != accrual_entry_id

    payment = api_client.get(f"/journal-entries/{payment_entry_id}").json()
    bridge_lines = [line for line in payment["lines"] if line["account_id"] == prepaid_id]
    assert len(bridge_lines) == 1
    assert Decimal(bridge_lines[0]["amount"]) == Decimal("800.00")

    accrual = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    accrual_account_ids = {line["account_id"] for line in accrual["lines"]}
    assert ap_id not in accrual_account_ids
    assert prepaid_id in accrual_account_ids


def test_manual_same_day_full_payment_collapses_into_accrual(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ap_id, _, obligation_id, accrual_entry_id, _ = _setup_repair_accrual_with_prepaid(
        api_client
    )

    r = api_client.post(
        "/journal-entries",
        json=_manual_payment_settlement_payload(
            entry_date=date(2026, 8, 1),
            cash_id=cash_id,
            bridge_id=ap_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("800.00"),
        ),
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == accrual_entry_id
    assert _count_rows(integration_db_url, "journal_entries") == 1
