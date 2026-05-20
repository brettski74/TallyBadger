"""Integration tests: CSV import obligation settlement via line[] (#151)."""

from __future__ import annotations

from collections.abc import Iterator
import hashlib
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
def ledger_service(integration_db_url: str) -> LedgerService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return LedgerService(connection_factory=connection_factory)


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


def _setup_rent_accrual(import_api_client: TestClient) -> tuple[int, int, int, int, int]:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    accounts = import_api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    cash_id = by_name["Cash"]
    ar_id = by_name["Accounts Receivable"]
    rent_id = by_name["Rent Revenue"]

    pr = import_api_client.post(
        "/parties",
        json={"name": "Pamela Tenant", "role": "customer", "is_active": True},
    )
    assert pr.status_code == 201, pr.text
    party_id = pr.json()["id"]

    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={"accounts_receivable_account_id": ar_id},
        ).status_code
        == 200
    )

    plan = import_api_client.post(
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

    obligations = import_api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    obligation_id = obligations[0]["id"]
    accrual_entry_id = obligations[0]["source_entry_id"]
    return party_id, cash_id, ar_id, obligation_id, accrual_entry_id


def _import_settlement_entry(
    ledger_service: LedgerService,
    *,
    entry_date: date,
    cash_id: int,
    ar_id: int,
    party_id: int,
    obligation_id: int,
    amount: Decimal,
    extra_lines: list[JournalLineIn] | None = None,
    basename: str = "settle.csv",
) -> tuple[int, list]:
    lines = [
        JournalLineIn(account_id=cash_id, party_id=party_id, amount=amount),
        JournalLineIn(
            account_id=ar_id,
            party_id=party_id,
            amount=-amount,
            obligation_id=obligation_id,
        ),
    ]
    if extra_lines:
        lines.extend(extra_lines)
    payload = JournalEntryWrite(
        entry_date=entry_date,
        summary="Rent receipt",
        lines=lines,
    )
    csv_bytes = f"{basename}-{amount}".encode()
    return ledger_service.create_import_batch_with_entries(
        basename=basename,
        content_sha256=hashlib.sha256(csv_bytes).digest(),
        payloads=[payload],
        confirm_duplicate_content=False,
    )


def test_import_settlement_single_obligation_updates_allocation(
    import_api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _ = _setup_rent_accrual(import_api_client)

    batch_id, created = _import_settlement_entry(
        ledger_service,
        entry_date=date(2026, 7, 15),
        cash_id=cash_id,
        ar_id=ar_id,
        party_id=party_id,
        obligation_id=obligation_id,
        amount=Decimal("1500.00"),
    )
    assert batch_id > 0
    assert len(created) == 1
    assert _count_rows(integration_db_url, "settlement_allocations") == 1
    assert _count_rows(integration_db_url, "journal_entries") == 2

    obligations = import_api_client.get(f"/obligations/{party_id}").json()
    assert obligations == []


def test_import_settlement_partial_leaves_obligation_open(
    import_api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _ = _setup_rent_accrual(import_api_client)

    _import_settlement_entry(
        ledger_service,
        entry_date=date(2026, 7, 15),
        cash_id=cash_id,
        ar_id=ar_id,
        party_id=party_id,
        obligation_id=obligation_id,
        amount=Decimal("500.00"),
        basename="partial.csv",
    )

    obligations = import_api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "partially_settled"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("1000.00")
    assert _count_rows(integration_db_url, "journal_entries") == 2


def test_import_same_day_full_receipt_collapses_into_accrual(
    import_api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, accrual_entry_id = _setup_rent_accrual(import_api_client)

    batch_id, created = _import_settlement_entry(
        ledger_service,
        entry_date=date(2026, 7, 1),
        cash_id=cash_id,
        ar_id=ar_id,
        party_id=party_id,
        obligation_id=obligation_id,
        amount=Decimal("1500.00"),
        basename="collapse.csv",
    )
    assert len(created) == 1
    assert created[0].id == accrual_entry_id
    assert _count_rows(integration_db_url, "journal_entries") == 1

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT import_batch_id FROM journal_entries WHERE id = %s",
                (accrual_entry_id,),
            )
            assert int(cur.fetchone()["import_batch_id"]) == batch_id


def test_import_non_same_day_creates_separate_journal(
    import_api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, accrual_entry_id = _setup_rent_accrual(import_api_client)

    _, created = _import_settlement_entry(
        ledger_service,
        entry_date=date(2026, 7, 15),
        cash_id=cash_id,
        ar_id=ar_id,
        party_id=party_id,
        obligation_id=obligation_id,
        amount=Decimal("1500.00"),
        basename="catchup.csv",
    )
    assert created[0].id != accrual_entry_id
    assert _count_rows(integration_db_url, "journal_entries") == 2


def test_unload_import_batch_reverses_settlement_allocations(
    import_api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    party_id, cash_id, ar_id, obligation_id, _ = _setup_rent_accrual(import_api_client)

    batch_id, _ = _import_settlement_entry(
        ledger_service,
        entry_date=date(2026, 7, 15),
        cash_id=cash_id,
        ar_id=ar_id,
        party_id=party_id,
        obligation_id=obligation_id,
        amount=Decimal("1500.00"),
        basename="unload.csv",
    )

    du = import_api_client.delete(f"/import-batches/{batch_id}")
    assert du.status_code == 204, du.text
    assert _count_rows(integration_db_url, "settlement_allocations") == 0
    assert _count_rows(integration_db_url, "import_batches") == 0

    obligations = import_api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "open"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("1500.00")


def test_csv_execute_rejects_unknown_obligation_id(
    import_api_client: TestClient,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    accounts = import_api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={"accounts_receivable_account_id": by_name["Accounts Receivable"]},
        ).status_code
        == 200
    )

    rule_set = {
        "name": "line builder",
        "rule_set": {
            "rules": [
                {
                    "sort_order": 10,
                    "expression": (
                        '{"set":{"line":[{"account":"Cash","amount":"100.00"},'
                        '{"account":"Accounts Receivable","amount":"-100.00","obligation-id":999}]}}'
                    ),
                },
            ],
        },
    }
    rs = import_api_client.post("/import-rules/cel/rule-sets", json=rule_set)
    assert rs.status_code == 201, rs.text
    rule_set_id = rs.json()["id"]

    ex = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": "date,summary\n2026-07-01,Bad obligation\n",
            "basename": "bad-ob.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
            ],
            "cel_rule_set_id": rule_set_id,
        },
    )
    assert ex.status_code == 422, ex.text
    detail = ex.json()["detail"]
    assert "obligation" in detail["row_errors"][0]["errors"][0].lower()
