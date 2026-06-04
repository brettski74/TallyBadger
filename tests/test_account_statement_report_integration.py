"""Integration tests for Account Statement report API."""

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
from tallybadger.main import app
from tallybadger.ledger.account_statement_report import (
    ACCOUNT_STATEMENT_PARTY_MULTI_LABEL,
    ACCOUNT_STATEMENT_PARTY_NONE_LABEL,
    BALANCE_FORWARD_SUMMARY,
    CLOSING_BALANCE_SUMMARY,
)
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn, PartyCreate
from tallybadger.ledger.service import JOURNAL_LIST_SPLIT_LABEL, LedgerService

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


def _seed_statement_data(ledger_service: LedgerService) -> int:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent Income", type="revenue"))
    expense = ledger_service.create_account(AccountCreate(name="Repairs", type="expense"))
    other_asset = ledger_service.create_account(AccountCreate(name="Petty Cash", type="asset"))
    tenant = ledger_service.create_party(PartyCreate(name="Tenant A", role="customer"))
    vendor = ledger_service.create_party(PartyCreate(name="Vendor B", role="vendor"))

    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 4, 30),
            summary="prior month deposit",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("100.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-100.00")),
            ],
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 5),
            summary="rent with tenant",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("200.00"), party_id=tenant.id),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-200.00"), party_id=tenant.id),
            ],
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 10),
            summary="split transfer",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("-30.00")),
                JournalLineIn(account_id=other_asset.id, amount=Decimal("15.00")),
                JournalLineIn(account_id=expense.id, amount=Decimal("15.00")),
            ],
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 12),
            summary="multi-party review item",
            requires_review=True,
            review_messages=["Needs review"],
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("-10.00"), party_id=tenant.id),
                JournalLineIn(account_id=expense.id, amount=Decimal("5.00"), party_id=tenant.id),
                JournalLineIn(account_id=expense.id, amount=Decimal("5.00"), party_id=vendor.id),
            ],
        )
    )
    return cash.id


def test_account_statement_json_labels_balances_and_review(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    cash_id = _seed_statement_data(ledger_service)
    r = api_client.get(
        "/reports/account-statement",
        params={"account_id": cash_id, "start_date": "2026-05-01", "end_date": "2026-05-31"},
    )
    assert r.status_code == 200
    body = r.json()
    assert Decimal(body["balance_forward"]) == Decimal("100.00")
    assert Decimal(body["closing_balance"]) == Decimal("260.00")

    rows = body["rows"]
    assert rows[0]["summary"] == BALANCE_FORWARD_SUMMARY
    assert rows[-1]["summary"] == CLOSING_BALANCE_SUMMARY

    activity = [row for row in rows if row["row_kind"] == "activity"]
    assert len(activity) == 3
    assert activity[0]["summary"] == "rent with tenant"
    assert activity[0]["counterparty_account"] == "Rent Income"
    assert activity[0]["party"] == "Tenant A"
    assert activity[0]["debit"] == "200.00"
    assert activity[0]["credit"] is None

    split_row = next(row for row in activity if row["summary"] == "split transfer")
    assert split_row["counterparty_account"] == JOURNAL_LIST_SPLIT_LABEL
    assert split_row["party"] == ACCOUNT_STATEMENT_PARTY_NONE_LABEL
    assert split_row["credit"] == "30.00"

    review_row = next(row for row in activity if row["summary"] == "multi-party review item")
    assert review_row["party"] == ACCOUNT_STATEMENT_PARTY_MULTI_LABEL

    assert Decimal(activity[-1]["balance"]) == Decimal("260.00")
    assert Decimal(body["closing_balance"]) == Decimal(body["balance_forward"]) + sum(
        Decimal(row["debit"] or "0") - Decimal(row["credit"] or "0") for row in activity
    )


def test_account_statement_unknown_account_404(api_client: TestClient) -> None:
    r = api_client.get(
        "/reports/account-statement",
        params={"account_id": 99999, "start_date": "2026-05-01", "end_date": "2026-05-31"},
    )
    assert r.status_code == 404


def test_account_statement_missing_dates_422(api_client: TestClient, ledger_service: LedgerService) -> None:
    cash_id = _seed_statement_data(ledger_service)
    r = api_client.get("/reports/account-statement", params={"account_id": cash_id})
    assert r.status_code == 422


def test_account_statement_csv_and_pdf_export(
    api_client: TestClient, ledger_service: LedgerService
) -> None:
    cash_id = _seed_statement_data(ledger_service)
    params = {"account_id": cash_id, "start_date": "2026-05-01", "end_date": "2026-05-31"}

    csv_r = api_client.get("/reports/account-statement/export", params={**params, "format": "csv"})
    assert csv_r.status_code == 200
    assert "attachment" in csv_r.headers.get("content-disposition", "").lower()
    assert "account-statement_Cash" in csv_r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(csv_r.text)))
    assert any(r["summary"] == BALANCE_FORWARD_SUMMARY for r in rows)

    pdf_r = api_client.get("/reports/account-statement/export", params={**params, "format": "pdf"})
    assert pdf_r.status_code == 200
    reader = PdfReader(io.BytesIO(pdf_r.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Cash Statement" in text
    assert CLOSING_BALANCE_SUMMARY in text
