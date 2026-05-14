"""Integration tests: CSV import orchestration (#40)."""

from __future__ import annotations

from collections.abc import Iterator
import os
from contextlib import contextmanager
from decimal import Decimal

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
def clean_import_tables(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE import_templates, journal_lines, journal_entry_attachments,
                      attachments, journal_entries, import_batches,
                      accrual_plans, parties, accounts, cel_rule_sets
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
    from tallybadger.api.routes.import_csv import get_ledger_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    app.dependency_overrides[get_ledger_service] = lambda: LedgerService(
        connection_factory=connection_factory,
    )
    app.dependency_overrides[get_cel_rule_set_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    app.dependency_overrides[get_csv_cel_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_ledger_service, None)
    app.dependency_overrides.pop(get_cel_rule_set_service, None)
    app.dependency_overrides.pop(get_csv_cel_service, None)


def _count_rows(integration_db_url: str, table: str) -> int:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
            return int(cur.fetchone()["c"])


def _ensure_ledger_settings_row(integration_db_url: str) -> None:
    with connect(integration_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ledger_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
            )


def test_csv_import_posts_all_rows_atomically(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Rent July,Cash,Rent Revenue,1200.00\n2026-08-01,Rent Aug,Cash,Rent Revenue,1300.00\n"
    payload = {
        "csv_text": csv_text,
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "dr-account", "data_type": "string"},
            {"attribute_name": "cr-account", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["posted_entries"] == 2
    assert body["dropped_rows"] == 0
    assert len(body["entries"]) == 2
    assert _count_rows(integration_db_url, "journal_entries") == 2
    assert _count_rows(integration_db_url, "journal_lines") == 4


def test_csv_import_aggregates_row_errors_and_rolls_back(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Rent July,Cash,Rent Revenue,1200.00\n2026-08-01,Rent Aug,Cash,Missing Rev,1300.00\n"
    payload = {
        "csv_text": csv_text,
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "dr-account", "data_type": "string"},
            {"attribute_name": "cr-account", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["message"] == "CSV import failed validation"
    assert detail["row_errors"][0]["row_number"] == 3
    assert "unknown account 'Missing Rev'" in detail["row_errors"][0]["errors"][0]
    assert _count_rows(integration_db_url, "journal_entries") == 0
    assert _count_rows(integration_db_url, "journal_lines") == 0


def test_csv_import_applies_optional_cel_rule_set(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={
            "name": "line-builder",
            "rule_set": {
                "rules": [
                    {
                        "sort_order": 0,
                        "expression": '{"set":{"summary":"CEL built","line":[{"account":"Cash","amount": 55},{"account":"Rent Revenue","amount": -55}]}}',
                        "captures": [],
                    },
                ],
            },
        },
    )
    assert rs.status_code == 201, rs.text
    rule_set_id = rs.json()["id"]

    payload = {
        "csv_text": "date\n2026-09-10\n",
        "has_header_row": True,
        "cel_rule_set_id": rule_set_id,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
        ],
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["posted_entries"] == 1
    assert body["entries"][0]["summary"] == "CEL built"
    lines = body["entries"][0]["lines"]
    assert len(lines) == 2
    assert Decimal(lines[0]["amount"]) == Decimal("55")
    assert Decimal(lines[1]["amount"]) == Decimal("-55")
    assert _count_rows(integration_db_url, "journal_entries") == 1


def test_csv_import_errors_when_unallocated_debit_missing_and_not_configured(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    for payload in (
        {"name": "Chequing", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Mystery,,Rent Revenue,50.00\n"
    payload = {
        "csv_text": csv_text,
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "dr-account", "data_type": "string"},
            {"attribute_name": "cr-account", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["row_errors"][0]["errors"]
    assert any("unallocated" in e.lower() for e in detail["row_errors"][0]["errors"])


def test_csv_import_defaults_unallocated_debit_and_marks_requires_review(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    created: dict[str, int] = {}
    for name, typ in (
        ("Chequing", "asset"),
        ("Unallocated Debits", "suspense"),
        ("Unallocated Credits", "suspense"),
        ("Rent Revenue", "revenue"),
    ):
        r = import_api_client.post("/accounts", json={"name": name, "type": typ, "is_active": True})
        assert r.status_code == 201, r.text
        created[name] = r.json()["id"]

    patch = import_api_client.patch(
        "/ledger-settings",
        json={
            "unallocated_debits_account_id": created["Unallocated Debits"],
            "unallocated_credits_account_id": created["Unallocated Credits"],
        },
    )
    assert patch.status_code == 200, patch.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Mystery,,Rent Revenue,50.00\n"
    payload = {
        "csv_text": csv_text,
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string"},
            {"attribute_name": "dr-account", "data_type": "string"},
            {"attribute_name": "cr-account", "data_type": "string"},
            {"attribute_name": "amount", "data_type": "numeric"},
        ],
    }
    r = import_api_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entries"][0]["requires_review"] is True
    rev = body["entries"][0]["review_messages"]
    assert len(rev) == 1
    assert rev[0]["message"] == "The debit amount is unallocated."
    lines = body["entries"][0]["lines"]
    debit_names = [ln["account_name"] for ln in lines if Decimal(ln["amount"]) > 0]
    credit_names = [ln["account_name"] for ln in lines if Decimal(ln["amount"]) < 0]
    assert debit_names == ["Unallocated Debits"]
    assert credit_names == ["Rent Revenue"]


def test_csv_import_execute_default_import_account_avoids_unallocated_and_review_flag(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    created: dict[str, int] = {}
    for name, typ in (
        ("Chequing", "asset"),
        ("Unallocated Debits", "suspense"),
        ("Unallocated Credits", "suspense"),
        ("Rent Revenue", "revenue"),
    ):
        r = import_api_client.post("/accounts", json={"name": name, "type": typ, "is_active": True})
        assert r.status_code == 201, r.text
        created[name] = r.json()["id"]

    patch = import_api_client.patch(
        "/ledger-settings",
        json={
            "unallocated_debits_account_id": created["Unallocated Debits"],
            "unallocated_credits_account_id": created["Unallocated Credits"],
        },
    )
    assert patch.status_code == 200, patch.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Mystery,,Rent Revenue,50.00\n"
    base_columns = [
        {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
        {"attribute_name": "summary", "data_type": "string"},
        {"attribute_name": "dr-account", "data_type": "string"},
        {"attribute_name": "cr-account", "data_type": "string"},
        {"attribute_name": "amount", "data_type": "numeric"},
    ]

    r_explicit = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": csv_text,
            "has_header_row": True,
            "default_import_account_id": created["Chequing"],
            "default_import_normal_balance": "debit",
            "columns": base_columns,
        },
    )
    assert r_explicit.status_code == 200, r_explicit.text
    body_explicit = r_explicit.json()
    assert body_explicit["entries"][0]["requires_review"] is False
    assert body_explicit["entries"][0]["review_messages"] == []
    lines_e = body_explicit["entries"][0]["lines"]
    assert [ln["account_name"] for ln in lines_e if Decimal(ln["amount"]) > 0] == ["Chequing"]
    assert [ln["account_name"] for ln in lines_e if Decimal(ln["amount"]) < 0] == ["Rent Revenue"]

    r_infer = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": csv_text,
            "has_header_row": True,
            "default_import_account_id": created["Chequing"],
            "columns": base_columns,
        },
    )
    assert r_infer.status_code == 200, r_infer.text
    body_infer = r_infer.json()
    assert body_infer["entries"][0]["requires_review"] is False
    assert body_infer["entries"][0]["review_messages"] == []
    lines_i = body_infer["entries"][0]["lines"]
    assert [ln["account_name"] for ln in lines_i if Decimal(ln["amount"]) > 0] == ["Chequing"]


def test_ledger_settings_rejects_non_suspense_unallocated_account(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    r = import_api_client.post("/accounts", json={"name": "Cash", "type": "asset", "is_active": True})
    assert r.status_code == 201, r.text
    cash_id = r.json()["id"]
    r2 = import_api_client.patch(
        "/ledger-settings",
        json={"unallocated_debits_account_id": cash_id},
    )
    assert r2.status_code == 422, r2.text
    assert "suspense" in r2.json()["detail"].lower()

