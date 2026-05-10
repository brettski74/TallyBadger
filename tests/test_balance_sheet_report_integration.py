"""Integration tests for Balance Sheet report API and aggregation."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import csv
import io
import os

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row
from pypdf import PdfReader

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn
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
def clean_database(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE import_templates, journal_lines, journal_entry_attachments,
                      attachments, journal_entries,
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
def api_client(integration_db_url: str) -> Iterator[TestClient]:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    app.dependency_overrides[get_ledger_service] = lambda: LedgerService(
        connection_factory=connection_factory,
    )
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_ledger_service, None)


def _seed_balance_sheet_data(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    loan = ledger_service.create_account(AccountCreate(name="Loan", type="liability"))
    owner_equity = ledger_service.create_account(AccountCreate(name="Owner Contributions", type="equity"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent Income", type="revenue"))
    expense = ledger_service.create_account(AccountCreate(name="Repairs", type="expense"))

    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 1, 1),
            summary="initial capital",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("1000.00")),
                JournalLineIn(account_id=owner_equity.id, amount=Decimal("-1000.00")),
            ],
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 1, 10),
            summary="rent collected",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("300.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-300.00")),
            ],
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 1, 12),
            summary="repair pending review",
            description=None,
            requires_review=True,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("-50.00")),
                JournalLineIn(account_id=expense.id, amount=Decimal("50.00")),
            ],
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 1, 15),
            summary="loan draw",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("200.00")),
                JournalLineIn(account_id=loan.id, amount=Decimal("-200.00")),
            ],
        )
    )


def test_balance_sheet_includes_retained_earnings_and_balances(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    _seed_balance_sheet_data(ledger_service)
    r = api_client.get("/reports/balance-sheet", params={"as_of_date": "2026-01-31"})
    assert r.status_code == 200
    b = r.json()
    assert b["exclude_requires_review"] is False
    assert b["assets"]["label"] == "Assets"
    assert Decimal(b["assets"]["total"]) == Decimal("1450.00")
    assert Decimal(b["liabilities"]["total"]) == Decimal("200.00")
    assert Decimal(b["equity"]["total"]) == Decimal("1250.00")
    retained = next((x for x in b["equity"]["accounts"] if x["account_name"] == "Retained Earnings"), None)
    assert retained is not None
    assert retained["is_computed"] is True
    assert Decimal(retained["amount"]) == Decimal("250.00")
    assert b["balance_check"]["is_balanced"] is True
    assert Decimal(b["balance_check"]["liabilities_plus_equity"]) == Decimal("1450.00")


def test_balance_sheet_excludes_requires_review_when_requested(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    _seed_balance_sheet_data(ledger_service)
    full = api_client.get("/reports/balance-sheet", params={"as_of_date": "2026-01-31"}).json()
    filtered = api_client.get(
        "/reports/balance-sheet", params={"as_of_date": "2026-01-31", "exclude_requires_review": "true"}
    ).json()
    assert Decimal(full["assets"]["total"]) == Decimal("1450.00")
    assert Decimal(filtered["assets"]["total"]) == Decimal("1500.00")
    full_retained = next(x for x in full["equity"]["accounts"] if x["account_name"] == "Retained Earnings")
    filtered_retained = next(x for x in filtered["equity"]["accounts"] if x["account_name"] == "Retained Earnings")
    assert Decimal(full_retained["amount"]) == Decimal("250.00")
    assert Decimal(filtered_retained["amount"]) == Decimal("300.00")


def test_balance_sheet_preset_prior_year_end(api_client: TestClient, ledger_service: LedgerService) -> None:
    _seed_balance_sheet_data(ledger_service)
    r = api_client.get(
        "/reports/balance-sheet",
        params={"preset": "prior_year_end", "preset_anchor_date": "2026-05-06"},
    )
    assert r.status_code == 200
    assert r.json()["period"]["as_of_date"] == "2025-12-31"


def test_balance_sheet_csv_export_matches_json(api_client: TestClient, ledger_service: LedgerService) -> None:
    _seed_balance_sheet_data(ledger_service)
    js = api_client.get("/reports/balance-sheet", params={"as_of_date": "2026-01-31"}).json()
    raw = api_client.get(
        "/reports/balance-sheet/export",
        params={"format": "csv", "as_of_date": "2026-01-31"},
    )
    assert raw.status_code == 200
    assert "balance-sheet" in raw.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(raw.content.decode("utf-8"))))
    fields = [r[0] for r in rows[1:] if r and r[0]]
    assert fields.index("asset") < fields.index("assets_total")
    assert fields.index("liability") < fields.index("liabilities_total")
    assert fields.index("equity_computed") < fields.index("equity_total")
    by_field = {r[0]: r for r in rows[1:] if r and len(r) >= 3}
    assert Decimal(by_field["assets_total"][2]) == Decimal(js["assets"]["total"])
    assert Decimal(by_field["liabilities_total"][2]) == Decimal(js["liabilities"]["total"])
    assert Decimal(by_field["equity_total"][2]) == Decimal(js["equity"]["total"])
    assert Decimal(by_field["liabilities_plus_equity"][2]) == Decimal(js["balance_check"]["liabilities_plus_equity"])


def test_balance_sheet_pdf_export_contains_labels(api_client: TestClient, ledger_service: LedgerService) -> None:
    try:
        from tallybadger.api.income_expense_export import resolve_pdf_unicode_font_path

        resolve_pdf_unicode_font_path()
    except RuntimeError as exc:
        pytest.skip(f"Unicode PDF font not available: {exc}")
    _seed_balance_sheet_data(ledger_service)
    raw = api_client.get(
        "/reports/balance-sheet/export",
        params={"format": "pdf", "as_of_date": "2026-01-31"},
    )
    assert raw.status_code == 200
    assert raw.headers["content-type"].startswith("application/pdf")
    text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw.content)).pages)
    assert "Balance Sheet" in text
    assert "Retained Earnings" in text
    assert "Liabilities + equity" in text
