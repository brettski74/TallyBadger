"""Integration tests: CSV import ``settlement`` attribute auto-builds line[] (#152)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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
def import_api_client(integration_db_url: str) -> Iterator[TestClient]:
    from tallybadger.api.routes.cel_rule_sets import get_cel_rule_set_service
    from tallybadger.api.routes.import_csv import get_cel_rule_set_service as get_csv_cel_service
    from tallybadger.api.routes.import_csv import get_ledger_service as get_import_ledger_service
    from tallybadger.api.routes.ledger import get_ledger_service as get_ledger_ledger_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    def _ledger() -> LedgerService:
        return LedgerService(connection_factory=connection_factory)

    app.dependency_overrides[get_import_ledger_service] = _ledger
    app.dependency_overrides[get_ledger_ledger_service] = _ledger
    app.dependency_overrides[get_cel_rule_set_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    app.dependency_overrides[get_csv_cel_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_import_ledger_service, None)
    app.dependency_overrides.pop(get_ledger_ledger_service, None)
    app.dependency_overrides.pop(get_cel_rule_set_service, None)
    app.dependency_overrides.pop(get_csv_cel_service, None)


def _count_rows(integration_db_url: str, table: str) -> int:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
            return int(cur.fetchone()["c"])


def _configure_unallocated(import_api_client: TestClient) -> None:
    for payload in (
        {"name": "Unallocated Debits", "type": "suspense", "is_active": True},
        {"name": "Unallocated Credits", "type": "suspense", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201
    by_name = {a["name"]: a["id"] for a in import_api_client.get("/accounts").json()}
    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={
                "unallocated_debits_account_id": by_name["Unallocated Debits"],
                "unallocated_credits_account_id": by_name["Unallocated Credits"],
            },
        ).status_code
        == 200
    )


def _setup_rent_receipt_context(import_api_client: TestClient) -> dict[str, int | str]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201
    by_name = {a["name"]: a["id"] for a in import_api_client.get("/accounts").json()}
    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={"accounts_receivable_account_id": by_name["Accounts Receivable"]},
        ).status_code
        == 200
    )
    pr = import_api_client.post(
        "/parties",
        json={"name": "Pamela Tenant", "role": "customer", "is_active": True},
    )
    assert pr.status_code == 201
    party_id = pr.json()["id"]
    plan = import_api_client.post(
        "/accrual-plans",
        json={
            "name": "July rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": by_name["Rent Revenue"],
            "frequency": "monthly_day",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "amount": "1500.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201
    obligation_id = import_api_client.get(f"/obligations/{party_id}").json()[0]["id"]
    return {
        "cash_id": by_name["Cash"],
        "rent_id": by_name["Rent Revenue"],
        "ar_id": by_name["Accounts Receivable"],
        "party_id": party_id,
        "obligation_id": obligation_id,
    }


def _create_settlement_rule_set(
    import_api_client: TestClient,
    *,
    extra_set_fields: str = "",
    settlement: str = "receipt",
) -> int:
    extra = f", {extra_set_fields}" if extra_set_fields else ""
    expression = (
        '{"set": {'
        f'"settlement": "{settlement}", '
        '"summary": attributes["summary"], '
        '"amount": attributes["amount"], '
        '"date": attributes["date"], '
        '"cr-account": "Rent Revenue", '
        f'"cr-party": "Pamela Tenant"{extra}'
        "}}"
    )
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "auto settlement", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    )
    assert rs.status_code == 201, rs.text
    return rs.json()["id"]


def _execute_csv(
    import_api_client: TestClient,
    *,
    rule_set_id: int,
    cash_id: int,
    amount: str,
    entry_date: str = "2026-07-15",
    summary: str = "Pamela rent",
) -> dict:
    payload = {
        "csv_text": f"date,summary,amount\n{entry_date},{summary},{amount}\n",
        "basename": "auto-settle.csv",
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
        "cel_rule_set_id": rule_set_id,
        "default_import_account_id": cash_id,
        "default_import_normal_balance": "debit",
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_auto_settlement_receipt_closes_obligation(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    ctx = _setup_rent_receipt_context(import_api_client)
    rule_set_id = _create_settlement_rule_set(import_api_client)
    data = _execute_csv(
        import_api_client,
        rule_set_id=rule_set_id,
        cash_id=int(ctx["cash_id"]),
        amount="1500.00",
    )
    assert data["posted_entries"] == 1
    assert _count_rows(integration_db_url, "settlement_allocations") == 1
    obligations = import_api_client.get(f"/obligations/{ctx['party_id']}").json()
    assert obligations == []

    entry = data["entries"][0]
    rent_lines = [ln for ln in entry["lines"] if ln["account_name"] == "Rent Revenue"]
    assert rent_lines == []


def test_auto_settlement_and_line_array_mutual_exclusion(
    import_api_client: TestClient,
) -> None:
    ctx = _setup_rent_receipt_context(import_api_client)
    expression = (
        '{"set": {"settlement": "receipt", "summary": "x", "amount": "100.00", "date": "2026-07-15", '
        '"cr-account": "Rent Revenue", "cr-party": "Pamela Tenant", '
        '"line": [{"account":"Cash","amount":"100.00"},{"account":"Rent Revenue","amount":"-100.00"}]}}'
    )
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "bad", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    )
    assert rs.status_code == 201
    payload = {
        "csv_text": "date,summary\n2026-07-15,x\n",
        "basename": "mutual.csv",
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
        ],
        "cel_rule_set_id": rs.json()["id"],
        "default_import_account_id": ctx["cash_id"],
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 422, r.text
    assert "line[]" in r.json()["detail"]["row_errors"][0]["errors"][0]


def test_auto_settlement_partial_allocation(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    ctx = _setup_rent_receipt_context(import_api_client)
    rule_set_id = _create_settlement_rule_set(import_api_client)
    data = _execute_csv(
        import_api_client,
        rule_set_id=rule_set_id,
        cash_id=int(ctx["cash_id"]),
        amount="500.00",
    )
    assert data["posted_entries"] == 1
    assert _count_rows(integration_db_url, "settlement_allocations") == 1
    obligations = import_api_client.get(f"/obligations/{ctx['party_id']}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "partially_settled"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("1000.00")


def test_auto_settlement_overpay_remainder_and_review(
    import_api_client: TestClient,
) -> None:
    ctx = _setup_rent_receipt_context(import_api_client)
    rule_set_id = _create_settlement_rule_set(import_api_client)
    data = _execute_csv(
        import_api_client,
        rule_set_id=rule_set_id,
        cash_id=int(ctx["cash_id"]),
        amount="1700.00",
    )
    entry = data["entries"][0]
    assert entry["requires_review"] is True
    rent = [ln for ln in entry["lines"] if ln["account_name"] == "Rent Revenue"]
    assert len(rent) == 1
    assert Decimal(rent[0]["amount"]) == Decimal("-200.00")


def test_auto_settlement_no_obligations_simple_post_and_review(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    _configure_unallocated(import_api_client)
    ctx = _setup_rent_receipt_context(import_api_client)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "TRUNCATE settlement_allocations, accrual_obligations RESTART IDENTITY CASCADE",
                )
    rule_set_id = _create_settlement_rule_set(import_api_client)
    data = _execute_csv(
        import_api_client,
        rule_set_id=rule_set_id,
        cash_id=int(ctx["cash_id"]),
        amount="500.00",
    )
    entry = data["entries"][0]
    assert entry["requires_review"] is True
    assert _count_rows(integration_db_url, "settlement_allocations") == 0
    assert len(entry["lines"]) == 2
    assert any("obligations" in m["message"].lower() for m in entry["review_messages"])


def test_auto_settlement_failed_preconditions_simple_post_and_review(
    import_api_client: TestClient,
) -> None:
    _configure_unallocated(import_api_client)
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201
    cash_id = next(a["id"] for a in import_api_client.get("/accounts").json() if a["name"] == "Cash")
    expression = (
        '{"set": {"settlement": "receipt", "summary": attributes["summary"], '
        '"amount": attributes["amount"], "date": attributes["date"], "cr-account": "Rent Revenue"}}'
    )
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "no party", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    )
    assert rs.status_code == 201
    payload = {
        "csv_text": "date,summary,amount\n2026-07-15,Rent,500.00\n",
        "basename": "precond.csv",
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
        "cel_rule_set_id": rs.json()["id"],
        "default_import_account_id": cash_id,
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 200, r.text
    entry = r.json()["entries"][0]
    assert entry["requires_review"] is True
    assert any("cr-party" in m["message"] for m in entry["review_messages"])


def test_auto_settlement_second_row_after_first_closes_obligation_posts_with_review(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    """Second auto-settlement row sees the first row's allocation; no duplicate settle in one import."""
    ctx = _setup_rent_receipt_context(import_api_client)
    rule_set_id = _create_settlement_rule_set(import_api_client)
    payload = {
        "csv_text": (
            "date,summary,amount\n"
            "2026-07-15,Pamela rent,1500.00\n"
            "2026-07-16,Pamela rent again,1500.00\n"
        ),
        "basename": "dup-obligation.csv",
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
        "cel_rule_set_id": rule_set_id,
        "default_import_account_id": ctx["cash_id"],
        "default_import_normal_balance": "debit",
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["posted_entries"] == 2
    assert _count_rows(integration_db_url, "settlement_allocations") == 1
    first, second = data["entries"]
    assert not first["requires_review"]
    assert second["requires_review"] is True
    assert any(
        "obligations" in m["message"].lower() for m in second["review_messages"]
    )
    obligations = import_api_client.get(f"/obligations/{ctx['party_id']}").json()
    assert obligations == []


def test_auto_settlement_unset_uses_simple_path(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    _configure_unallocated(import_api_client)
    ctx = _setup_rent_receipt_context(import_api_client)
    expression = (
        '{"set": {"summary": attributes["summary"], "amount": attributes["amount"], '
        '"date": attributes["date"], "dr-account": "Cash", "cr-account": "Rent Revenue", '
        '"cr-party": "Pamela Tenant"}}'
    )
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "plain", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    )
    assert rs.status_code == 201
    data = _execute_csv(
        import_api_client,
        rule_set_id=rs.json()["id"],
        cash_id=int(ctx["cash_id"]),
        amount="1500.00",
    )
    assert _count_rows(integration_db_url, "settlement_allocations") == 0
    assert data["entries"][0]["requires_review"] is False


def test_auto_settlement_payment_closes_payable(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201
    by_name = {a["name"]: a["id"] for a in import_api_client.get("/accounts").json()}
    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={"accounts_payable_account_id": by_name["Accounts Payable"]},
        ).status_code
        == 200
    )
    pr = import_api_client.post(
        "/parties",
        json={"name": "Vendor Co", "role": "vendor", "is_active": True},
    )
    assert pr.status_code == 201
    party_id = pr.json()["id"]
    plan = import_api_client.post(
        "/accrual-plans",
        json={
            "name": "Repair bill",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": by_name["Repairs Expense"],
            "frequency": "monthly_day",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "amount": "800.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201

    expression = (
        '{"set": {"settlement": "payment", "summary": attributes["summary"], '
        '"amount": attributes["amount"], "date": attributes["date"], '
        '"dr-account": "Repairs Expense", "dr-party": "Vendor Co", "cr-account": "Cash"}}'
    )
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "pay vendor", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    )
    assert rs.status_code == 201
    payload = {
        "csv_text": "date,summary,amount\n2026-08-15,Pay vendor,800.00\n",
        "basename": "payment.csv",
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
        "cel_rule_set_id": rs.json()["id"],
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 200, r.text
    assert _count_rows(integration_db_url, "settlement_allocations") == 1
    assert import_api_client.get(f"/obligations/{party_id}").json() == []


def test_auto_settlement_payment_uses_per_obligation_bridge_accounts(
    import_api_client: TestClient,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
        {"name": "Prepaid Expenses", "type": "asset", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201
    by_name = {a["name"]: a["id"] for a in import_api_client.get("/accounts").json()}
    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={
                "accounts_payable_account_id": by_name["Accounts Payable"],
                "prepaid_expenses_account_id": by_name["Prepaid Expenses"],
            },
        ).status_code
        == 200
    )

    pr = import_api_client.post(
        "/parties",
        json={"name": "Vendor Bridge Split", "role": "vendor", "is_active": True},
    )
    assert pr.status_code == 201
    party_id = pr.json()["id"]
    plan = import_api_client.post(
        "/accrual-plans",
        json={
            "name": "Two-month payable",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": by_name["Repairs Expense"],
            "frequency": "monthly_day",
            "start_date": "2026-08-01",
            "end_date": "2026-09-01",
            "amount": "400.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text

    expression = (
        '{"set": {"settlement": "payment", "summary": attributes["summary"], '
        '"amount": attributes["amount"], "date": attributes["date"], '
        '"dr-account": "Repairs Expense", "dr-party": "Vendor Bridge Split", "cr-account": "Cash"}}'
    )
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "pay mixed obligations", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    )
    assert rs.status_code == 201

    payload = {
        "csv_text": "date,summary,amount\n2026-08-15,Pay vendor mixed,600.00\n",
        "basename": "payment-bridge-split.csv",
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
        "cel_rule_set_id": rs.json()["id"],
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 200, r.text
    entry = r.json()["entries"][0]

    ap_lines = [ln for ln in entry["lines"] if ln["account_name"] == "Accounts Payable"]
    prepaid_lines = [ln for ln in entry["lines"] if ln["account_name"] == "Prepaid Expenses"]
    assert len(ap_lines) == 1
    assert len(prepaid_lines) == 1
    assert Decimal(ap_lines[0]["amount"]) == Decimal("400.00")
    assert Decimal(prepaid_lines[0]["amount"]) == Decimal("200.00")


def test_auto_settlement_with_cheque_on_same_row(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    ctx = _setup_rent_receipt_context(import_api_client)
    ch = import_api_client.post(
        "/cheques",
        json={
            "credit_account_id": ctx["cash_id"],
            "debit_account_id": ctx["rent_id"],
            "summary": "Pamela rent cheque",
            "cheque_number": 1001,
            "issue_date": "2026-07-15",
            "amount": "1500.00",
            "party_id": ctx["party_id"],
        },
    )
    assert ch.status_code == 201, ch.text
    cheque_id = ch.json()["id"]

    rule_set_id = _create_settlement_rule_set(
        import_api_client,
        extra_set_fields=f'"cheque-id": {cheque_id}',
    )
    data = _execute_csv(
        import_api_client,
        rule_set_id=rule_set_id,
        cash_id=int(ctx["cash_id"]),
        amount="1500.00",
    )
    entry = data["entries"][0]
    assert entry["cheque_id"] == cheque_id
    assert _count_rows(integration_db_url, "settlement_allocations") == 1
