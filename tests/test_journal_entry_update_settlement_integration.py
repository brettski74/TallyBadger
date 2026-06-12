"""Integration tests: PUT journal entry with settlement reversal and reapply (#271)."""

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
from tallybadger.ledger.models import AccountCreate, AccrualPlanCreate, LedgerSettingsUpdate, PartyCreate
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
                      cheques,
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


def _count_rows(integration_db_url: str, table: str) -> int:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
            return int(cur.fetchone()["c"])


def _setup_rent_accrual(api_client: TestClient) -> tuple[int, int, int, int, int, int]:
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
    return party_id, cash_id, ar_id, obligation_id, accrual_entry_id, rent_id


def _settlement_payload(
    *,
    entry_date: date,
    cash_id: int,
    ar_id: int,
    party_id: int,
    obligation_id: int | None,
    amount: Decimal,
    summary: str = "Rent receipt",
    cheque_id: int | None = None,
) -> dict:
    lines = [
        {"account_id": cash_id, "party_id": party_id, "amount": str(amount)},
    ]
    if obligation_id is not None:
        lines.append(
            {
                "account_id": ar_id,
                "party_id": party_id,
                "amount": str(-amount),
                "obligation_id": obligation_id,
            }
        )
    else:
        lines.append(
            {
                "account_id": ar_id,
                "party_id": party_id,
                "amount": str(-amount),
            }
        )
    body: dict = {
        "entry_date": entry_date.isoformat(),
        "summary": summary,
        "lines": lines,
    }
    if cheque_id is not None:
        body["cheque_id"] = cheque_id
    return body


def _create_settlement_entry(
    api_client: TestClient,
    *,
    party_id: int,
    cash_id: int,
    ar_id: int,
    obligation_id: int,
    amount: Decimal = Decimal("1500.00"),
    entry_date: date = date(2026, 7, 15),
) -> int:
    r = api_client.post(
        "/journal-entries",
        json=_settlement_payload(
            entry_date=entry_date,
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=amount,
        ),
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_put_increases_settlement_amount_and_updates_allocation_fk(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _, _ = _setup_rent_accrual(api_client)
    entry_id = _create_settlement_entry(
        api_client,
        party_id=party_id,
        cash_id=cash_id,
        ar_id=ar_id,
        obligation_id=obligation_id,
        amount=Decimal("500.00"),
    )

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert Decimal(obligations[0]["open_amount"]) == Decimal("1000.00")

    put = api_client.put(
        f"/journal-entries/{entry_id}",
        json=_settlement_payload(
            entry_date=date(2026, 7, 16),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("1000.00"),
            summary="Increased rent receipt",
        ),
    )
    assert put.status_code == 200, put.text
    assert put.json()["id"] == entry_id

    entry = api_client.get(f"/journal-entries/{entry_id}").json()
    assert len(entry["settlement_allocations"]) == 1
    alloc = entry["settlement_allocations"][0]
    assert Decimal(alloc["amount"]) == Decimal("1000.00")
    bridge = next(line for line in entry["lines"] if line["account_id"] == ar_id)
    assert bridge["settlement_allocation_id"] == alloc["id"]

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert Decimal(obligations[0]["open_amount"]) == Decimal("500.00")
    assert _count_rows(integration_db_url, "settlement_allocations") == 1


def test_put_clears_obligation_lines_and_restores_open_balance(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _, rent_id = _setup_rent_accrual(api_client)
    entry_id = _create_settlement_entry(
        api_client,
        party_id=party_id,
        cash_id=cash_id,
        ar_id=ar_id,
        obligation_id=obligation_id,
    )

    put = api_client.put(
        f"/journal-entries/{entry_id}",
        json={
            "entry_date": "2026-07-16",
            "summary": "Plain journal after edit",
            "lines": [
                {"account_id": cash_id, "party_id": party_id, "amount": "1500.00"},
                {"account_id": rent_id, "party_id": party_id, "amount": "-1500.00"},
            ],
        },
    )
    assert put.status_code == 200, put.text

    entry = api_client.get(f"/journal-entries/{entry_id}").json()
    assert entry["settlement_allocations"] == []
    assert all(line.get("settlement_allocation_id") is None for line in entry["lines"])
    assert _count_rows(integration_db_url, "settlement_allocations") == 0

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "open"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("1500.00")


def test_put_rejects_accrual_plan_journal_entry(
    api_client: TestClient,
) -> None:
    party_id, cash_id, ar_id, obligation_id, accrual_entry_id, _ = _setup_rent_accrual(api_client)

    put = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_settlement_payload(
            entry_date=date(2026, 7, 1),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("1500.00"),
        ),
    )
    assert put.status_code == 422, put.text
    detail = put.json()["detail"].lower()
    assert "accrual plan" in detail
    assert "july rent" in detail


def test_put_settlement_update_keeps_cheque_register_in_sync(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _, _ = _setup_rent_accrual(api_client)
    bank = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))

    ch = api_client.post(
        "/cheques",
        json={
            "credit_account_id": bank.id,
            "debit_account_id": ar_id,
            "summary": "Rent cheque",
            "cheque_number": 42,
            "issue_date": "2026-07-10",
            "amount": "1500.00",
        },
    )
    assert ch.status_code == 201, ch.text
    cheque_id = ch.json()["id"]

    entry_id = _create_settlement_entry(
        api_client,
        party_id=party_id,
        cash_id=cash_id,
        ar_id=ar_id,
        obligation_id=obligation_id,
    )

    put = api_client.put(
        f"/journal-entries/{entry_id}",
        json=_settlement_payload(
            entry_date=date(2026, 7, 15),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("1500.00"),
            cheque_id=cheque_id,
        ),
    )
    assert put.status_code == 200, put.text

    reg = api_client.get(f"/cheques/{cheque_id}").json()
    assert reg["status"] == "cleared"
    assert reg["cleared_date"] == "2026-07-15"

    unlink = api_client.put(
        f"/journal-entries/{entry_id}",
        json=_settlement_payload(
            entry_date=date(2026, 7, 15),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("1500.00"),
        ),
    )
    assert unlink.status_code == 200, unlink.text

    reg = api_client.get(f"/cheques/{cheque_id}").json()
    assert reg["status"] == "open"
    assert reg["cleared_date"] is None


def test_put_same_day_collapse_merges_into_accrual_entry(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, accrual_entry_id, _ = _setup_rent_accrual(api_client)
    entry_id = _create_settlement_entry(
        api_client,
        party_id=party_id,
        cash_id=cash_id,
        ar_id=ar_id,
        obligation_id=obligation_id,
        entry_date=date(2026, 7, 15),
    )
    assert entry_id != accrual_entry_id
    assert _count_rows(integration_db_url, "journal_entries") == 2

    put = api_client.put(
        f"/journal-entries/{entry_id}",
        json=_settlement_payload(
            entry_date=date(2026, 7, 1),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("1500.00"),
        ),
    )
    assert put.status_code == 200, put.text
    assert put.json()["id"] == accrual_entry_id
    assert _count_rows(integration_db_url, "journal_entries") == 1

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert len(entry["settlement_allocations"]) == 1
    assert api_client.get(f"/journal-entries/{entry_id}").status_code == 404


def _setup_early_payment_accrual(api_client: TestClient) -> tuple[int, int, int, int, int, int]:
    for payload in (
        {"name": "Chequing", "type": "asset", "is_active": True},
        {"name": "Yard Maintenance", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
        {"name": "Prepaid Expenses", "type": "asset", "is_active": True},
    ):
        assert api_client.post("/accounts", json=payload).status_code == 201

    accounts = api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    cash_id = by_name["Chequing"]
    ap_id = by_name["Accounts Payable"]
    expense_id = by_name["Yard Maintenance"]
    prepaid_id = by_name["Prepaid Expenses"]

    pr = api_client.post(
        "/parties",
        json={"name": "Mower Man", "role": "vendor", "is_active": True},
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
            "name": "May yard",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": expense_id,
            "frequency": "monthly_day",
            "start_date": "2026-05-01",
            "end_date": "2026-05-31",
            "amount": "101.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    obligation_id = obligations[0]["id"]
    return party_id, cash_id, prepaid_id, obligation_id, expense_id, ap_id


def test_put_clears_payment_settlement_when_cash_line_has_no_party(
    api_client: TestClient,
    integration_db_url: str,
) -> None:
    party_id, cash_id, prepaid_id, obligation_id, expense_id, _ = _setup_early_payment_accrual(
        api_client
    )

    create = api_client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-04-28",
            "summary": "CHEQUE - # 55",
            "lines": [
                {"account_id": cash_id, "party_id": None, "amount": "-101.00"},
                {
                    "account_id": prepaid_id,
                    "party_id": party_id,
                    "amount": "101.00",
                    "obligation_id": obligation_id,
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    entry_id = int(create.json()["id"])

    put = api_client.put(
        f"/journal-entries/{entry_id}",
        json={
            "entry_date": "2026-04-28",
            "summary": "CHEQUE - # 55",
            "lines": [
                {"account_id": cash_id, "party_id": None, "amount": "-101.00"},
                {"account_id": expense_id, "party_id": party_id, "amount": "101.00"},
            ],
        },
    )
    assert put.status_code == 200, put.text

    entry = api_client.get(f"/journal-entries/{entry_id}").json()
    assert entry["settlement_allocations"] == []
    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "open"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("101.00")
