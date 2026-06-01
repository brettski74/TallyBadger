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
                    TRUNCATE TABLE
                      settlement_allocations,
                      accrual_obligations,
                      import_templates,
                      journal_entry_review_messages,
                      journal_lines,
                      journal_entry_attachments,
                      attachments,
                      journal_entries,
                      cheques,
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
        "basename": "rent-import.csv",
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
    batch_id = body["import_batch_id"]
    assert isinstance(batch_id, int)
    assert body["basename"] == "rent-import.csv"
    assert _count_rows(integration_db_url, "import_batches") == 1
    assert _count_rows(integration_db_url, "journal_entries") == 2
    assert _count_rows(integration_db_url, "journal_lines") == 4
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT import_batch_id FROM journal_entries WHERE import_batch_id IS NOT NULL",
            )
            rows = cur.fetchall()
            assert len(rows) == 1
            assert int(rows[0]["import_batch_id"]) == batch_id


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
        "basename": "bad-row.csv",
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
        "basename": "cel-one-row.csv",
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
        "basename": "unalloc-missing.csv",
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
        "basename": "unalloc-defaulted.csv",
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
            "basename": "explicit-default.csv",
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
            "basename": "inferred-default.csv",
            "has_header_row": True,
            "default_import_account_id": created["Chequing"],
            "columns": base_columns,
            # Same bytes as the first execute: duplicate content guard otherwise returns 409.
            "confirm_duplicate_content": True,
        },
    )
    assert r_infer.status_code == 200, r_infer.text
    body_infer = r_infer.json()
    assert body_infer["entries"][0]["requires_review"] is False
    assert body_infer["entries"][0]["review_messages"] == []
    lines_i = body_infer["entries"][0]["lines"]
    assert [ln["account_name"] for ln in lines_i if Decimal(ln["amount"]) > 0] == ["Chequing"]


def test_csv_import_header_only_yields_zero_posts_and_no_import_batch(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    payload = {
        "csv_text": "date,summary,dr,cr,amount\n",
        "basename": "header-only.csv",
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
    assert body["posted_entries"] == 0
    assert body["dropped_rows"] == 0
    assert body["import_batch_id"] is None
    assert _count_rows(integration_db_url, "import_batches") == 0
    assert _count_rows(integration_db_url, "journal_entries") == 0


def test_csv_import_duplicate_content_requires_confirm_then_posts(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Rent July,Cash,Rent Revenue,1200.00\n"
    base = {
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
    r1 = import_api_client.post("/imports/csv/execute", json={**base, "basename": "first-pass.csv"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["import_batch_id"] is not None

    r_dup = import_api_client.post("/imports/csv/execute", json={**base, "basename": "second-name.csv"})
    assert r_dup.status_code == 409, r_dup.text
    detail = r_dup.json()["detail"]
    assert detail["code"] == "duplicate_import_content"
    assert "confirm_duplicate_content" in detail["message"].lower()

    r_ok = import_api_client.post(
        "/imports/csv/execute",
        json={**base, "basename": "second-name.csv", "confirm_duplicate_content": True},
    )
    assert r_ok.status_code == 200, r_ok.text
    assert _count_rows(integration_db_url, "import_batches") == 2
    assert _count_rows(integration_db_url, "journal_entries") == 2


def test_csv_import_active_basename_case_conflict_returns_409(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_a = "date,summary,dr,cr,amount\n2026-07-01,A,Cash,Rent Revenue,10.00\n"
    csv_b = "date,summary,dr,cr,amount\n2026-07-02,B,Cash,Rent Revenue,20.00\n"
    cols = [
        {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
        {"attribute_name": "summary", "data_type": "string"},
        {"attribute_name": "dr-account", "data_type": "string"},
        {"attribute_name": "cr-account", "data_type": "string"},
        {"attribute_name": "amount", "data_type": "numeric"},
    ]
    r1 = import_api_client.post(
        "/imports/csv/execute",
        json={"csv_text": csv_a, "basename": "Stmt.csv", "has_header_row": True, "columns": cols},
    )
    assert r1.status_code == 200, r1.text

    r2 = import_api_client.post(
        "/imports/csv/execute",
        json={"csv_text": csv_b, "basename": "stmt.csv", "has_header_row": True, "columns": cols},
    )
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert detail["code"] == "import_basename_conflict"


def test_csv_import_normalizes_basename_to_final_path_segment(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,X,Cash,Rent Revenue,1.00\n"
    cols = [
        {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
        {"attribute_name": "summary", "data_type": "string"},
        {"attribute_name": "dr-account", "data_type": "string"},
        {"attribute_name": "cr-account", "data_type": "string"},
        {"attribute_name": "amount", "data_type": "numeric"},
    ]
    r = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": csv_text,
            "basename": "/tmp/nested/LedgerExport.csv",
            "has_header_row": True,
            "columns": cols,
        },
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["import_batch_id"]
    assert batch_id is not None
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT basename FROM import_batches WHERE id = %s", (batch_id,))
            row = cur.fetchone()
            assert row is not None
            assert row["basename"] == "LedgerExport.csv"


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
    detail = r2.json()["detail"]
    if isinstance(detail, dict):
        message = " ".join(detail.get("errors", []))
    else:
        message = str(detail)
    assert "suspense" in message.lower()
    assert "Unallocated debits" in message


def test_get_import_batches_lists_loaded_batches(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Rent,Cash,Rent Revenue,100.00\n"
    ex = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": csv_text,
            "basename": "list-batches-test.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "dr-account", "data_type": "string"},
                {"attribute_name": "cr-account", "data_type": "string"},
                {"attribute_name": "amount", "data_type": "numeric"},
            ],
        },
    )
    assert ex.status_code == 200, ex.text
    assert ex.json()["basename"] == "list-batches-test.csv"

    r = import_api_client.get("/import-batches")
    assert r.status_code == 200, r.text
    batches = r.json()
    assert any(b["basename"] == "list-batches-test.csv" for b in batches)
    latest = next(b for b in batches if b["basename"] == "list-batches-test.csv")
    assert latest["is_latest_loaded_import"] is True


def test_journal_entries_filter_by_import_basename_case_insensitive(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Rent,Cash,Rent Revenue,50.00\n"
    ex = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": csv_text,
            "basename": "FilterMe.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "dr-account", "data_type": "string"},
                {"attribute_name": "cr-account", "data_type": "string"},
                {"attribute_name": "amount", "data_type": "numeric"},
            ],
        },
    )
    assert ex.status_code == 200, ex.text

    jr = import_api_client.get("/journal-entries", params={"import_basename": "filterme.csv"})
    assert jr.status_code == 200, jr.text
    entries = jr.json()
    assert len(entries) == 1
    assert entries[0]["summary"] == "Rent"


def test_list_journal_entries_rejects_import_batch_id_and_basename_together(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        r = import_api_client.post("/accounts", json=payload)
        assert r.status_code == 201, r.text

    csv_text = "date,summary,dr,cr,amount\n2026-07-01,Rent,Cash,Rent Revenue,10.00\n"
    ex = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": csv_text,
            "basename": "both-filters.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "dr-account", "data_type": "string"},
                {"attribute_name": "cr-account", "data_type": "string"},
                {"attribute_name": "amount", "data_type": "numeric"},
            ],
        },
    )
    assert ex.status_code == 200, ex.text
    bid = ex.json()["import_batch_id"]

    r = import_api_client.get(
        "/journal-entries",
        params={"import_batch_id": bid, "import_basename": "both-filters.csv"},
    )
    assert r.status_code == 422, r.text
    assert "both" in str(r.json()["detail"]).lower()


def test_unload_import_batch_returns_404_when_already_unloaded(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    ex = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": "date,summary,dr,cr,amount\n2026-07-01,Rent,Cash,Rent Revenue,10.00\n",
            "basename": "unload-twice.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "dr-account", "data_type": "string"},
                {"attribute_name": "cr-account", "data_type": "string"},
                {"attribute_name": "amount", "data_type": "numeric"},
            ],
        },
    )
    assert ex.status_code == 200, ex.text
    batch_id = ex.json()["import_batch_id"]
    assert batch_id is not None

    d1 = import_api_client.delete(f"/import-batches/{batch_id}")
    assert d1.status_code == 204, d1.text
    d2 = import_api_client.delete(f"/import-batches/{batch_id}")
    assert d2.status_code == 404, d2.text
    assert "unload" in d2.json()["detail"].lower() or "not found" in d2.json()["detail"].lower()
    assert _count_rows(integration_db_url, "import_batches") == 0
    assert _count_rows(integration_db_url, "journal_entries") == 0


def test_unload_import_batch_rolls_back_same_day_receipt_settlement(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    accounts = import_api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    ar_id = by_name["Accounts Receivable"]
    rent_id = by_name["Rent Revenue"]

    pr = import_api_client.post(
        "/parties",
        json={"name": "Tenant Unload", "role": "customer", "is_active": True},
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
            "name": "July unload rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": rent_id,
            "bridge_account_id": ar_id,
            "frequency": "monthly_day",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "amount": "500.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text
    obligation_id = import_api_client.get(f"/obligations/{party_id}").json()[0]["id"]

    rule_set = {
        "name": "same-day settle lines",
        "rule_set": {
            "rules": [
                {
                    "sort_order": 10,
                    "expression": (
                        '{"set":{"line":['
                        '{"account":"Cash","amount":attributes["amt"],"party":"Tenant Unload"},'
                        '{"account":"Accounts Receivable","amount":-attributes["amt"],'
                        '"party":"Tenant Unload","obligation-id":'
                        + str(obligation_id)
                        + "}]}}"
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
            "csv_text": "date,summary,amt\n2026-07-01,July rent receipt,500.00\n",
            "basename": "settle-then-unload.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "amt", "data_type": "numeric"},
            ],
            "cel_rule_set_id": rule_set_id,
        },
    )
    assert ex.status_code == 200, ex.text
    batch_id = ex.json()["import_batch_id"]
    assert _count_rows(integration_db_url, "journal_entries") == 1
    assert _count_rows(integration_db_url, "settlement_allocations") == 1

    du = import_api_client.delete(f"/import-batches/{batch_id}")
    assert du.status_code == 204, du.text
    assert _count_rows(integration_db_url, "import_batches") == 0
    assert _count_rows(integration_db_url, "journal_entries") == 1
    assert _count_rows(integration_db_url, "settlement_allocations") == 0

    obligations = import_api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "open"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("500.00")


def test_unload_import_batch_rolls_back_same_day_payment_settlement(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    accounts = import_api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    ap_id = by_name["Accounts Payable"]
    repairs_id = by_name["Repairs Expense"]

    pr = import_api_client.post(
        "/parties",
        json={"name": "Vendor Unload", "role": "vendor", "is_active": True},
    )
    assert pr.status_code == 201, pr.text
    party_id = pr.json()["id"]

    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={"accounts_payable_account_id": ap_id},
        ).status_code
        == 200
    )

    plan = import_api_client.post(
        "/accrual-plans",
        json={
            "name": "July unload payable",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": repairs_id,
            "bridge_account_id": ap_id,
            "frequency": "monthly_day",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "amount": "500.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text
    obligation_id = import_api_client.get(f"/obligations/{party_id}").json()[0]["id"]

    rule_set = {
        "name": "same-day settle payment lines",
        "rule_set": {
            "rules": [
                {
                    "sort_order": 10,
                    "expression": (
                        '{"set":{"line":['
                        '{"account":"Cash","amount":-attributes["amt"],"party":"Vendor Unload"},'
                        '{"account":"Accounts Payable","amount":attributes["amt"],'
                        '"party":"Vendor Unload","obligation-id":'
                        + str(obligation_id)
                        + "}]}}"
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
            "csv_text": "date,summary,amt\n2026-07-01,July vendor payment,500.00\n",
            "basename": "settle-payment-then-unload.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "amt", "data_type": "numeric"},
            ],
            "cel_rule_set_id": rule_set_id,
        },
    )
    assert ex.status_code == 200, ex.text
    batch_id = ex.json()["import_batch_id"]
    assert _count_rows(integration_db_url, "journal_entries") == 1
    assert _count_rows(integration_db_url, "settlement_allocations") == 1

    du = import_api_client.delete(f"/import-batches/{batch_id}")
    assert du.status_code == 204, du.text
    assert _count_rows(integration_db_url, "import_batches") == 0
    assert _count_rows(integration_db_url, "journal_entries") == 1
    assert _count_rows(integration_db_url, "settlement_allocations") == 0

    obligations = import_api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "open"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("500.00")


def test_unload_import_batch_reverses_early_payment_prepaid_reclassification(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
        {"name": "Prepaid Expenses", "type": "asset", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    accounts = import_api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    ap_id = by_name["Accounts Payable"]
    prepaid_id = by_name["Prepaid Expenses"]
    repairs_id = by_name["Repairs Expense"]

    pr = import_api_client.post(
        "/parties",
        json={"name": "Vendor Early Unload", "role": "vendor", "is_active": True},
    )
    assert pr.status_code == 201, pr.text
    party_id = pr.json()["id"]

    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={
                "accounts_payable_account_id": ap_id,
                "prepaid_expenses_account_id": prepaid_id,
            },
        ).status_code
        == 200
    )

    plan = import_api_client.post(
        "/accrual-plans",
        json={
            "name": "Aug early unload payable",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": repairs_id,
            "bridge_account_id": ap_id,
            "frequency": "monthly_day",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "amount": "500.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text
    obligation = import_api_client.get(f"/obligations/{party_id}").json()[0]
    obligation_id = obligation["id"]
    accrual_entry_id = obligation["source_entry_id"]

    rule_set = {
        "name": "early payment settle lines",
        "rule_set": {
            "rules": [
                {
                    "sort_order": 10,
                    "expression": (
                        '{"set":{"line":['
                        '{"account":"Cash","amount":-attributes["amt"],"party":"Vendor Early Unload"},'
                        '{"account":"Prepaid Expenses","amount":attributes["amt"],'
                        '"party":"Vendor Early Unload","obligation-id":'
                        + str(obligation_id)
                        + "}]}}"
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
            "csv_text": "date,summary,amt\n2026-07-15,Early vendor payment,500.00\n",
            "basename": "early-payment-then-unload.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "amt", "data_type": "numeric"},
            ],
            "cel_rule_set_id": rule_set_id,
        },
    )
    assert ex.status_code == 200, ex.text
    batch_id = ex.json()["import_batch_id"]
    assert _count_rows(integration_db_url, "settlement_allocations") == 1

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT account_id, amount
                FROM journal_lines
                WHERE entry_id = %s
                ORDER BY id ASC
                """,
                (accrual_entry_id,),
            )
            before = cur.fetchall()
    assert any(int(r["account_id"]) == prepaid_id for r in before)
    assert not any(int(r["account_id"]) == ap_id for r in before)

    du = import_api_client.delete(f"/import-batches/{batch_id}")
    assert du.status_code == 204, du.text
    assert _count_rows(integration_db_url, "settlement_allocations") == 0

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT account_id, amount
                FROM journal_lines
                WHERE entry_id = %s
                ORDER BY id ASC
                """,
                (accrual_entry_id,),
            )
            after = cur.fetchall()
    assert any(int(r["account_id"]) == ap_id for r in after)
    assert not any(int(r["account_id"]) == prepaid_id for r in after)


def test_unload_import_batch_reverses_partial_early_payment_prepaid_split(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    """Unload must repoint obligation source_line_id before deleting split A/P lines (#231)."""
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Repairs Expense", "type": "expense", "is_active": True},
        {"name": "Accounts Payable", "type": "liability", "is_active": True},
        {"name": "Prepaid Expenses", "type": "asset", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    accounts = import_api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    ap_id = by_name["Accounts Payable"]
    prepaid_id = by_name["Prepaid Expenses"]
    repairs_id = by_name["Repairs Expense"]

    pr = import_api_client.post(
        "/parties",
        json={"name": "Vendor Partial Early", "role": "vendor", "is_active": True},
    )
    assert pr.status_code == 201, pr.text
    party_id = pr.json()["id"]

    assert (
        import_api_client.patch(
            "/ledger-settings",
            json={
                "accounts_payable_account_id": ap_id,
                "prepaid_expenses_account_id": prepaid_id,
            },
        ).status_code
        == 200
    )

    plan = import_api_client.post(
        "/accrual-plans",
        json={
            "name": "May partial unload payable",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": repairs_id,
            "bridge_account_id": ap_id,
            "frequency": "monthly_day",
            "start_date": "2026-05-01",
            "end_date": "2026-05-31",
            "amount": "234.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text
    obligation = import_api_client.get(f"/obligations/{party_id}").json()[0]
    obligation_id = obligation["id"]
    accrual_entry_id = obligation["source_entry_id"]

    expression = (
        '{"set": {"settlement": "payment", "summary": attributes["summary"], '
        '"amount": attributes["amount"], "date": attributes["date"], '
        '"dr-account": "Repairs Expense", "dr-party": "Vendor Partial Early", "cr-account": "Cash"}}'
    )
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "partial early pay", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    )
    assert rs.status_code == 201
    ex = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": "date,summary,amount\n2026-04-29,Partial early vendor payment,101.70\n",
            "basename": "partial-early-payment.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "amount", "data_type": "numeric"},
            ],
            "cel_rule_set_id": rs.json()["id"],
        },
    )
    assert ex.status_code == 200, ex.text
    batch_id = ex.json()["import_batch_id"]
    assert _count_rows(integration_db_url, "settlement_allocations") == 1

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT account_id, amount
                FROM journal_lines
                WHERE entry_id = %s
                ORDER BY id ASC
                """,
                (accrual_entry_id,),
            )
            before = cur.fetchall()
    assert sum(1 for r in before if int(r["account_id"]) == prepaid_id) == 1
    assert sum(1 for r in before if int(r["account_id"]) == ap_id) == 1

    du = import_api_client.delete(f"/import-batches/{batch_id}")
    assert du.status_code == 204, du.text
    assert _count_rows(integration_db_url, "settlement_allocations") == 0

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT account_id, amount
                FROM journal_lines
                WHERE entry_id = %s
                ORDER BY id ASC
                """,
                (accrual_entry_id,),
            )
            after = cur.fetchall()
    assert len(after) == 2
    assert sum(1 for r in after if int(r["account_id"]) == ap_id) == 1
    assert not any(int(r["account_id"]) == prepaid_id for r in after)

    obligations = import_api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "open"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("234.00")


def test_unload_import_batch_same_day_payment_overpayment_without_collapse(
    import_api_client: TestClient,
    integration_db_url: str,
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
        json={"name": "Vendor Overpay", "role": "vendor", "is_active": True},
    )
    assert pr.status_code == 201
    party_id = pr.json()["id"]
    plan = import_api_client.post(
        "/accrual-plans",
        json={
            "name": "April repair",
            "direction": "expense",
            "party_id": party_id,
            "target_account_id": by_name["Repairs Expense"],
            "bridge_account_id": by_name["Accounts Payable"],
            "frequency": "monthly_day",
            "start_date": "2026-04-01",
            "end_date": "2026-04-30",
            "amount": "904.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201

    expression = (
        '{"set": {"settlement": "payment", "summary": attributes["summary"], '
        '"amount": attributes["amount"], "date": attributes["date"], '
        '"dr-account": "Repairs Expense", "dr-party": "Vendor Overpay", "cr-account": "Cash"}}'
    )
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "overpay vendor", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    )
    assert rs.status_code == 201
    ex = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": "date,summary,amount\n2026-04-01,Pay vendor over,1000.00\n",
            "basename": "overpay-no-collapse.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "amount", "data_type": "numeric"},
            ],
            "cel_rule_set_id": rs.json()["id"],
        },
    )
    assert ex.status_code == 200, ex.text
    batch_id = ex.json()["import_batch_id"]
    assert _count_rows(integration_db_url, "journal_entries") == 2

    du = import_api_client.delete(f"/import-batches/{batch_id}")
    assert du.status_code == 204, du.text
    assert _count_rows(integration_db_url, "import_batches") == 0
    assert _count_rows(integration_db_url, "settlement_allocations") == 0
    obligations = import_api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    assert obligations[0]["status"] == "open"
    assert Decimal(obligations[0]["open_amount"]) == Decimal("904.00")


def test_import_batches_is_latest_loaded_import_two_batches(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    cols = [
        {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
        {"attribute_name": "summary", "data_type": "string"},
        {"attribute_name": "dr-account", "data_type": "string"},
        {"attribute_name": "cr-account", "data_type": "string"},
        {"attribute_name": "amount", "data_type": "numeric"},
    ]
    assert (
        import_api_client.post(
            "/imports/csv/execute",
            json={
                "csv_text": "date,summary,dr,cr,amount\n2026-07-01,A,Cash,Rent Revenue,1.00\n",
                "basename": "older.csv",
                "has_header_row": True,
                "columns": cols,
            },
        ).status_code
        == 200
    )
    assert (
        import_api_client.post(
            "/imports/csv/execute",
            json={
                "csv_text": "date,summary,dr,cr,amount\n2026-07-02,B,Cash,Rent Revenue,2.00\n",
                "basename": "newer.csv",
                "has_header_row": True,
                "columns": cols,
            },
        ).status_code
        == 200
    )

    batches = import_api_client.get("/import-batches").json()
    by_base = {b["basename"]: b for b in batches}
    assert by_base["older.csv"]["is_latest_loaded_import"] is False
    assert by_base["newer.csv"]["is_latest_loaded_import"] is True


def test_unload_import_batch_reopens_cleared_cheque(
    import_api_client: TestClient,
    integration_db_url: str,
) -> None:
    for payload in (
        {"name": "Chequing", "type": "asset", "is_active": True},
        {"name": "Mowing", "type": "expense", "is_active": True},
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201

    accounts = import_api_client.get("/accounts").json()
    by_name = {a["name"]: a["id"] for a in accounts}
    cq = import_api_client.post(
        "/cheques",
        json={
            "credit_account_id": by_name["Chequing"],
            "debit_account_id": by_name["Mowing"],
            "summary": "Lawn",
            "cheque_number": 901,
            "issue_date": "2026-06-01",
            "amount": "88.00",
            "status": "open",
        },
    )
    assert cq.status_code == 201, cq.text
    cheque_id = cq.json()["id"]

    ex = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": "date,summary,dr,cr,amount\n2026-07-01,Rent,Cash,Rent Revenue,100.00\n",
            "basename": "cheque-unload.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "dr-account", "data_type": "string"},
                {"attribute_name": "cr-account", "data_type": "string"},
                {"attribute_name": "amount", "data_type": "numeric"},
            ],
        },
    )
    assert ex.status_code == 200, ex.text
    batch_id = ex.json()["import_batch_id"]
    entry_id = ex.json()["entries"][0]["id"]

    get_e = import_api_client.get(f"/journal-entries/{entry_id}")
    assert get_e.status_code == 200, get_e.text
    body = get_e.json()
    put_body = {
        "entry_date": body["entry_date"],
        "summary": body["summary"],
        "description": body["description"],
        "cheque_id": cheque_id,
        "lines": [{"account_id": ln["account_id"], "party_id": ln.get("party_id"), "amount": str(ln["amount"])} for ln in body["lines"]],
    }
    put_r = import_api_client.put(f"/journal-entries/{entry_id}", json=put_body)
    assert put_r.status_code == 200, put_r.text
    assert put_r.json()["cheque_id"] == cheque_id

    ch_row = import_api_client.get(f"/cheques/{cheque_id}").json()
    assert ch_row["status"] == "cleared"

    assert import_api_client.delete(f"/import-batches/{batch_id}").status_code == 204
    ch_after = import_api_client.get(f"/cheques/{cheque_id}").json()
    assert ch_after["status"] == "open"
    assert ch_after["cleared_date"] is None
