"""Integration tests for Income & Expense report API and ledger aggregation."""

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
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn
from tallybadger.ledger.service import LedgerService

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


def _sql_pl_totals(integration_db_url: str, start: date, end: date) -> tuple[Decimal, Decimal]:
    """Match service semantics: raw SUM(jl.amount) by type, then revenue → -raw, expense → raw."""
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN a.type = 'revenue' THEN jl.amount END), 0) AS raw_rev,
                       COALESCE(SUM(CASE WHEN a.type = 'expense' THEN jl.amount END), 0) AS raw_exp
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.entry_id
                JOIN accounts a ON a.id = jl.account_id
                WHERE je.entry_date >= %s AND je.entry_date <= %s
                  AND a.type IN ('revenue', 'expense')
                """,
                (start, end),
            )
            row = cur.fetchone()
    assert row is not None
    return -Decimal(row["raw_rev"]), Decimal(row["raw_exp"])


def test_income_expense_reconciles_to_sql_and_excludes_balance_sheet_lines(
    ledger_service: LedgerService,
    integration_db_url: str,
    api_client: TestClient,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rev_a = ledger_service.create_account(AccountCreate(name="Alpha Rent", type="revenue"))
    rev_b = ledger_service.create_account(AccountCreate(name="Beta Rent", type="revenue"))
    exp_a = ledger_service.create_account(AccountCreate(name="Gamma Repairs", type="expense"))

    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 3, 15),
            summary="rent",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("200.00")),
                JournalLineIn(account_id=rev_a.id, amount=Decimal("-120.00")),
                JournalLineIn(account_id=rev_b.id, amount=Decimal("-80.00")),
            ],
        ),
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 3, 20),
            summary="fix",
            description=None,
            requires_review=True,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("-45.00")),
                JournalLineIn(account_id=exp_a.id, amount=Decimal("45.00")),
            ],
        ),
    )

    start, end = date(2026, 3, 1), date(2026, 3, 31)
    sql_tr, sql_te = _sql_pl_totals(integration_db_url, start, end)

    r = api_client.get(
        "/reports/income-expense",
        params={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "exclude_zero_balance_accounts": "false",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert Decimal(body["total_revenue"]) == sql_tr == Decimal("200")
    assert Decimal(body["total_expense"]) == sql_te == Decimal("45")
    assert Decimal(body["net_income"]) == Decimal("155")

    rev_sum = sum(Decimal(x["amount"]) for x in body["revenue_accounts"])
    exp_sum = sum(Decimal(x["amount"]) for x in body["expense_accounts"])
    assert rev_sum == sql_tr
    assert exp_sum == sql_te

    names = [x["account_name"] for x in body["revenue_accounts"]]
    assert names == sorted(names)


def test_period_boundary_inclusive(
    ledger_service: LedgerService,
    api_client: TestClient,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rev = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))

    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 1),
            summary="on start",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("10")),
                JournalLineIn(account_id=rev.id, amount=Decimal("-10")),
            ],
        ),
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 10),
            summary="on end",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("5")),
                JournalLineIn(account_id=rev.id, amount=Decimal("-5")),
            ],
        ),
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 31),
            summary="before",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("100")),
                JournalLineIn(account_id=rev.id, amount=Decimal("-100")),
            ],
        ),
    )

    r = api_client.get(
        "/reports/income-expense",
        params={
            "start_date": "2026-06-01",
            "end_date": "2026-06-10",
        },
    )
    assert r.status_code == 200
    assert Decimal(r.json()["total_revenue"]) == Decimal("15")


def test_exclude_zero_balance_accounts_totals_unchanged(
    ledger_service: LedgerService,
    api_client: TestClient,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rev_on = ledger_service.create_account(AccountCreate(name="Zebra Rent", type="revenue"))
    rev_off = ledger_service.create_account(AccountCreate(name="Aardvark Rent", type="revenue"))

    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 1, 10),
            summary="only zebra",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("50")),
                JournalLineIn(account_id=rev_on.id, amount=Decimal("-50")),
            ],
        ),
    )

    start, end = date(2026, 1, 1), date(2026, 1, 31)
    full = api_client.get(
        "/reports/income-expense",
        params={"start_date": start.isoformat(), "end_date": end.isoformat(), "exclude_zero_balance_accounts": "false"},
    ).json()
    slim = api_client.get(
        "/reports/income-expense",
        params={"start_date": start.isoformat(), "end_date": end.isoformat(), "exclude_zero_balance_accounts": "true"},
    ).json()

    assert len(full["revenue_accounts"]) == 2
    assert len(slim["revenue_accounts"]) == 1
    assert slim["revenue_accounts"][0]["account_name"] == "Zebra Rent"
    assert Decimal(full["total_revenue"]) == Decimal(slim["total_revenue"]) == Decimal("50")


def test_empty_period(
    ledger_service: LedgerService,
    api_client: TestClient,
) -> None:
    ledger_service.create_account(AccountCreate(name="Idle Rev", type="revenue"))
    ledger_service.create_account(AccountCreate(name="Idle Exp", type="expense"))

    r = api_client.get(
        "/reports/income-expense",
        params={"start_date": "2026-02-01", "end_date": "2026-02-28", "exclude_zero_balance_accounts": "false"},
    )
    assert r.status_code == 200
    b = r.json()
    assert Decimal(b["total_revenue"]) == Decimal("0")
    assert len(b["revenue_accounts"]) == 1
    assert len(b["expense_accounts"]) == 1

    r2 = api_client.get(
        "/reports/income-expense",
        params={"start_date": "2026-02-01", "end_date": "2026-02-28", "exclude_zero_balance_accounts": "true"},
    )
    assert r2.json()["revenue_accounts"] == []
    assert r2.json()["expense_accounts"] == []


def test_preset_query_params(api_client: TestClient) -> None:
    r = api_client.get(
        "/reports/income-expense",
        params={"preset": "prior_full_year", "as_of_date": "2026-05-06"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["period"]["start_date"] == "2025-01-01"
    assert b["period"]["end_date"] == "2025-12-31"
    assert b["preset"] == "prior_full_year"


def test_csv_export_matches_json(api_client: TestClient, ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rev = ledger_service.create_account(AccountCreate(name="Q Rent", type="revenue"))
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 4, 1),
            summary="r",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("33.50")),
                JournalLineIn(account_id=rev.id, amount=Decimal("-33.50")),
            ],
        ),
    )
    start, end = date(2026, 4, 1), date(2026, 4, 30)
    js = api_client.get(
        "/reports/income-expense",
        params={"start_date": start.isoformat(), "end_date": end.isoformat()},
    ).json()
    raw = api_client.get(
        "/reports/income-expense/export",
        params={"format": "csv", "start_date": start.isoformat(), "end_date": end.isoformat()},
    )
    assert raw.status_code == 200
    assert "income-expense" in raw.headers["content-disposition"]
    decoded = raw.content.decode("utf-8")
    rows = list(csv.reader(io.StringIO(decoded)))
    by_field = {r[0]: r for r in rows[1:] if r and r[0] in ("total_revenue", "total_expense", "net_income")}
    assert Decimal(by_field["total_revenue"][2]) == Decimal(js["total_revenue"])
    assert Decimal(by_field["total_expense"][2]) == Decimal(js["total_expense"])
    assert Decimal(by_field["net_income"][2]) == Decimal(js["net_income"])


def test_pdf_export_contains_key_totals(api_client: TestClient, ledger_service: LedgerService) -> None:
    try:
        from tallybadger.api.income_expense_export import resolve_pdf_unicode_font_path

        resolve_pdf_unicode_font_path()
    except RuntimeError as exc:
        pytest.skip(f"Unicode PDF font not available: {exc}")

    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rev = ledger_service.create_account(AccountCreate(name="M Rent", type="revenue"))
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 7, 1),
            summary="r",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("99.25")),
                JournalLineIn(account_id=rev.id, amount=Decimal("-99.25")),
            ],
        ),
    )
    start, end = date(2026, 7, 1), date(2026, 7, 31)
    raw = api_client.get(
        "/reports/income-expense/export",
        params={"format": "pdf", "start_date": start.isoformat(), "end_date": end.isoformat()},
    )
    assert raw.status_code == 200
    assert raw.headers["content-type"].startswith("application/pdf")
    reader = PdfReader(io.BytesIO(raw.content))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert "Income" in text and "Expense" in text
    assert "99.25" in text
    assert "2026-07-01" in text
