"""Integration tests: journal entry settlement preview API (#221)."""

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


def _preview(api_client: TestClient, payload: dict) -> dict | None:
    response = api_client.post("/journal-entries/settlement-preview", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _setup_rent_accrual(api_client: TestClient, *, configure_ar: bool = True) -> dict[str, int]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201

    accounts = api_client.get("/accounts").json()
    by_name = {account["name"]: account["id"] for account in accounts}
    if configure_ar:
        assert (
            api_client.patch(
                "/ledger-settings",
                json={"accounts_receivable_account_id": by_name["Accounts Receivable"]},
            ).status_code
            == 200
        )

    party = api_client.post(
        "/parties",
        json={"name": "Pamela Tenant", "role": "customer", "is_active": True},
    )
    assert party.status_code == 201, party.text
    party_id = party.json()["id"]

    plan = api_client.post(
        "/accrual-plans",
        json={
            "name": "July rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": by_name["Rent Revenue"],
            "bridge_account_id": by_name["Accounts Receivable"],
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
    return {
        "party_id": party_id,
        "cash_id": by_name["Cash"],
        "rent_id": by_name["Rent Revenue"],
        "ar_id": by_name["Accounts Receivable"],
        "obligation_id": obligations[0]["id"],
    }


def _setup_payment_accrual(api_client: TestClient) -> dict[str, int]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201

    by_name = {account["name"]: account["id"] for account in api_client.get("/accounts").json()}
    assert (
        api_client.patch(
            "/ledger-settings",
            json={"accounts_payable_account_id": by_name["Accounts Payable"]},
        ).status_code
        == 200
    )

    party = api_client.post(
        "/parties",
        json={"name": "Vendor Co", "role": "vendor", "is_active": True},
    )
    assert party.status_code == 201
    party_id = party.json()["id"]

    plan = api_client.post(
        "/accrual-plans",
        json={
            "name": "Repair bill",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": by_name["Repairs Expense"],
            "bridge_account_id": by_name["Accounts Payable"],
            "frequency": "monthly_day",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "amount": "800.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    return {
        "party_id": party_id,
        "cash_id": by_name["Cash"],
        "expense_id": by_name["Repairs Expense"],
        "ap_id": by_name["Accounts Payable"],
        "obligation_id": obligations[0]["id"],
    }


def _receipt_draft(
    *,
    entry_date: date,
    cash_id: int,
    rent_id: int,
    party_id: int,
    amount: Decimal,
) -> dict:
    amount_str = str(amount)
    return {
        "entry_date": entry_date.isoformat(),
        "summary": "Rent receipt",
        "lines": [
            {"account_id": cash_id, "party_id": party_id, "amount": amount_str},
            {"account_id": rent_id, "party_id": party_id, "amount": str(-amount)},
        ],
    }


def test_preview_gate_skip_multi_party(api_client: TestClient) -> None:
    ctx = _setup_rent_accrual(api_client)
    other_party = api_client.post(
        "/parties",
        json={"name": "Other Tenant", "role": "customer", "is_active": True},
    )
    assert other_party.status_code == 201
    other_party_id = other_party.json()["id"]

    preview = _preview(
        api_client,
        {
            "entry_date": "2026-07-15",
            "summary": "Mixed parties",
            "lines": [
                {"account_id": ctx["cash_id"], "party_id": ctx["party_id"], "amount": "100.00"},
                {"account_id": ctx["rent_id"], "party_id": other_party_id, "amount": "-100.00"},
            ],
        },
    )
    assert preview is None


def test_preview_gate_skip_ambiguous_cash(api_client: TestClient) -> None:
    ctx = _setup_rent_accrual(api_client)
    bank = api_client.post("/accounts", json={"name": "Bank", "type": "asset", "is_active": True})
    assert bank.status_code == 201
    bank_id = bank.json()["id"]

    preview = _preview(
        api_client,
        {
            "entry_date": "2026-07-15",
            "summary": "Mixed cash signs",
            "lines": [
                {"account_id": ctx["cash_id"], "party_id": ctx["party_id"], "amount": "100.00"},
                {"account_id": bank_id, "party_id": ctx["party_id"], "amount": "-50.00"},
                {"account_id": ctx["rent_id"], "party_id": ctx["party_id"], "amount": "-50.00"},
            ],
        },
    )
    assert preview is None


def test_preview_gate_skip_missing_ar_config(api_client: TestClient) -> None:
    ctx = _setup_rent_accrual(api_client, configure_ar=False)

    preview = _preview(
        api_client,
        _receipt_draft(
            entry_date=date(2026, 7, 15),
            cash_id=ctx["cash_id"],
            rent_id=ctx["rent_id"],
            party_id=ctx["party_id"],
            amount=Decimal("1500.00"),
        ),
    )
    assert preview is None


def _setup_rent_accrual_with_unearned(api_client: TestClient) -> dict[str, int]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
        {"name": "Unearned Revenue", "type": "liability", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201

    by_name = {account["name"]: account["id"] for account in api_client.get("/accounts").json()}
    assert (
        api_client.patch(
            "/ledger-settings",
            json={
                "accounts_receivable_account_id": by_name["Accounts Receivable"],
                "unearned_revenue_account_id": by_name["Unearned Revenue"],
            },
        ).status_code
        == 200
    )

    party = api_client.post(
        "/parties",
        json={"name": "Early Payer", "role": "customer", "is_active": True},
    )
    assert party.status_code == 201, party.text
    party_id = party.json()["id"]

    plan = api_client.post(
        "/accrual-plans",
        json={
            "name": "July rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": by_name["Rent Revenue"],
            "bridge_account_id": by_name["Accounts Receivable"],
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
    return {
        "party_id": party_id,
        "cash_id": by_name["Cash"],
        "rent_id": by_name["Rent Revenue"],
        "ar_id": by_name["Accounts Receivable"],
        "ur_id": by_name["Unearned Revenue"],
        "obligation_id": obligations[0]["id"],
    }


def test_preview_early_receipt_uses_unearned_bridge(api_client: TestClient) -> None:
    ctx = _setup_rent_accrual_with_unearned(api_client)

    preview = _preview(
        api_client,
        _receipt_draft(
            entry_date=date(2026, 6, 26),
            cash_id=ctx["cash_id"],
            rent_id=ctx["rent_id"],
            party_id=ctx["party_id"],
            amount=Decimal("1500.00"),
        ),
    )
    assert preview is not None
    bridge_lines = [line for line in preview["lines"] if line.get("obligation_id") is not None]
    assert len(bridge_lines) == 1
    assert bridge_lines[0]["account_id"] == ctx["ur_id"]
    assert bridge_lines[0]["account_id"] != ctx["ar_id"]


def _setup_payment_accrual_with_prepaid(api_client: TestClient) -> dict[str, int]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
        {"name": "Prepaid Expenses", "type": "asset", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201

    by_name = {account["name"]: account["id"] for account in api_client.get("/accounts").json()}
    assert (
        api_client.patch(
            "/ledger-settings",
            json={
                "accounts_payable_account_id": by_name["Accounts Payable"],
                "prepaid_expenses_account_id": by_name["Prepaid Expenses"],
            },
        ).status_code
        == 200
    )

    party = api_client.post(
        "/parties",
        json={"name": "Early Vendor", "role": "vendor", "is_active": True},
    )
    assert party.status_code == 201, party.text
    party_id = party.json()["id"]

    plan = api_client.post(
        "/accrual-plans",
        json={
            "name": "August repair",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": by_name["Repairs Expense"],
            "bridge_account_id": by_name["Accounts Payable"],
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
    return {
        "party_id": party_id,
        "cash_id": by_name["Cash"],
        "expense_id": by_name["Repairs Expense"],
        "ap_id": by_name["Accounts Payable"],
        "prepaid_id": by_name["Prepaid Expenses"],
        "obligation_id": obligations[0]["id"],
    }


def test_preview_early_payment_uses_prepaid_bridge(api_client: TestClient) -> None:
    ctx = _setup_payment_accrual_with_prepaid(api_client)

    preview = _preview(
        api_client,
        {
            "entry_date": date(2026, 7, 26).isoformat(),
            "summary": "Early vendor payment",
            "lines": [
                {"account_id": ctx["expense_id"], "party_id": ctx["party_id"], "amount": "800.00"},
                {"account_id": ctx["cash_id"], "party_id": ctx["party_id"], "amount": "-800.00"},
            ],
        },
    )
    assert preview is not None
    bridge_lines = [line for line in preview["lines"] if line.get("obligation_id") is not None]
    assert len(bridge_lines) == 1
    assert bridge_lines[0]["account_id"] == ctx["prepaid_id"]
    assert bridge_lines[0]["account_id"] != ctx["ap_id"]


def test_preview_receipt_full_match(api_client: TestClient) -> None:
    ctx = _setup_rent_accrual(api_client)

    preview = _preview(
        api_client,
        _receipt_draft(
            entry_date=date(2026, 7, 15),
            cash_id=ctx["cash_id"],
            rent_id=ctx["rent_id"],
            party_id=ctx["party_id"],
            amount=Decimal("1500.00"),
        ),
    )
    assert preview is not None
    assert preview["party_id"] == ctx["party_id"]
    assert preview["party_name"] == "Pamela Tenant"
    assert Decimal(preview["receipt_cash_amount"]) == Decimal("1500.00")
    assert preview["payment_cash_amount"] is None
    assert len(preview["allocations"]) == 1
    allocation = preview["allocations"][0]
    assert allocation["obligation_id"] == ctx["obligation_id"]
    assert allocation["source_entry_summary"] == "July rent"
    assert allocation["settlement_type"] == "receipt"
    assert Decimal(allocation["applied_amount"]) == Decimal("1500.00")

    bridge_lines = [line for line in preview["lines"] if line.get("obligation_id") is not None]
    assert len(bridge_lines) == 1
    assert bridge_lines[0]["account_id"] == ctx["ar_id"]
    assert Decimal(bridge_lines[0]["amount"]) == Decimal("-1500.00")
    assert sum(Decimal(line["amount"]) for line in preview["lines"]) == Decimal("0")


def test_preview_payment_full_match(api_client: TestClient) -> None:
    ctx = _setup_payment_accrual(api_client)

    preview = _preview(
        api_client,
        {
            "entry_date": "2026-08-15",
            "summary": "Pay vendor",
            "lines": [
                {"account_id": ctx["expense_id"], "party_id": ctx["party_id"], "amount": "800.00"},
                {"account_id": ctx["cash_id"], "party_id": ctx["party_id"], "amount": "-800.00"},
            ],
        },
    )
    assert preview is not None
    assert Decimal(preview["payment_cash_amount"]) == Decimal("800.00")
    assert preview["receipt_cash_amount"] is None
    assert preview["allocations"][0]["settlement_type"] == "payment"
    assert preview["allocations"][0]["source_entry_summary"] == "Repair bill"
    bridge_lines = [line for line in preview["lines"] if line.get("obligation_id") is not None]
    assert len(bridge_lines) == 1
    assert bridge_lines[0]["account_id"] == ctx["ap_id"]
    assert Decimal(bridge_lines[0]["amount"]) == Decimal("800.00")


def test_preview_receipt_partial_fifo_and_remainder(api_client: TestClient) -> None:
    ctx = _setup_rent_accrual(api_client)

    preview = _preview(
        api_client,
        _receipt_draft(
            entry_date=date(2026, 7, 15),
            cash_id=ctx["cash_id"],
            rent_id=ctx["rent_id"],
            party_id=ctx["party_id"],
            amount=Decimal("500.00"),
        ),
    )
    assert preview is not None
    assert Decimal(preview["allocations"][0]["applied_amount"]) == Decimal("500.00")

    lines_by_account = {line["account_id"]: line for line in preview["lines"]}
    assert Decimal(lines_by_account[ctx["ar_id"]]["amount"]) == Decimal("-500.00")
    assert ctx["rent_id"] not in lines_by_account


def test_preview_no_obligations_returns_null(api_client: TestClient) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201
    by_name = {account["name"]: account["id"] for account in api_client.get("/accounts").json()}
    assert (
        api_client.patch(
            "/ledger-settings",
            json={"accounts_receivable_account_id": by_name["Accounts Receivable"]},
        ).status_code
        == 200
    )
    party = api_client.post(
        "/parties",
        json={"name": "No Accrual Tenant", "role": "customer", "is_active": True},
    )
    assert party.status_code == 201
    party_id = party.json()["id"]

    preview = _preview(
        api_client,
        _receipt_draft(
            entry_date=date(2026, 7, 15),
            cash_id=by_name["Cash"],
            rent_id=by_name["Rent Revenue"],
            party_id=party_id,
            amount=Decimal("100.00"),
        ),
    )
    assert preview is None


def test_preview_combined_receipt_and_payment_for_one_party(api_client: TestClient) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201
    by_name = {account["name"]: account["id"] for account in api_client.get("/accounts").json()}
    assert (
        api_client.patch(
            "/ledger-settings",
            json={
                "accounts_receivable_account_id": by_name["Accounts Receivable"],
                "accounts_payable_account_id": by_name["Accounts Payable"],
            },
        ).status_code
        == 200
    )

    party = api_client.post(
        "/parties",
        json={"name": "Dual Role Co", "role": "both", "is_active": True},
    )
    assert party.status_code == 201
    party_id = party.json()["id"]

    for body in (
        {
            "name": "July rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": by_name["Rent Revenue"],
            "bridge_account_id": by_name["Accounts Receivable"],
            "frequency": "monthly_day",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "amount": "100.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
        {
            "name": "Repair bill",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": by_name["Repairs Expense"],
            "bridge_account_id": by_name["Accounts Payable"],
            "frequency": "monthly_day",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "amount": "50.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    ):
        assert api_client.post("/accrual-plans", json=body).status_code == 201

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 2

    preview = _preview(
        api_client,
        {
            "entry_date": "2026-08-15",
            "summary": "Combined movement",
            "lines": [
                {"account_id": by_name["Cash"], "party_id": party_id, "amount": "100.00"},
                {"account_id": by_name["Rent Revenue"], "party_id": party_id, "amount": "-100.00"},
                {"account_id": by_name["Repairs Expense"], "party_id": party_id, "amount": "50.00"},
                {"account_id": by_name["Cash"], "party_id": party_id, "amount": "-50.00"},
            ],
        },
    )
    assert preview is not None
    assert Decimal(preview["receipt_cash_amount"]) == Decimal("100.00")
    assert Decimal(preview["payment_cash_amount"]) == Decimal("50.00")
    assert len(preview["allocations"]) == 2
    settlement_types = {item["settlement_type"] for item in preview["allocations"]}
    assert settlement_types == {"receipt", "payment"}
    assert sum(Decimal(line["amount"]) for line in preview["lines"]) == Decimal("0")

    obligation_lines = [line for line in preview["lines"] if line.get("obligation_id") is not None]
    assert len(obligation_lines) == 2
