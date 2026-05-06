"""Unit tests for Income & Expense preset resolution and P&L sign mapping."""

from contextlib import contextmanager
import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from tallybadger.api.income_expense_export import (
    income_expense_report_csv_bytes,
    income_expense_report_pdf_bytes,
    resolve_pdf_unicode_font_path,
)
from tallybadger.ledger.income_expense_report import (
    natural_pl_total_for_account_type,
    resolve_income_expense_preset,
    same_calendar_day_prior_year,
)
from tallybadger.ledger.models import (
    IncomeExpenseAccountRowOut,
    IncomeExpensePeriodEcho,
    IncomeExpenseReportOut,
)
from tallybadger.ledger.service import LedgerService, LedgerValidationError


@contextmanager
def _connection_should_not_open():
    raise AssertionError("database should not open for this validation-only path")
    yield  # pragma: no cover


def test_same_calendar_day_prior_year_leap_to_non_leap() -> None:
    assert same_calendar_day_prior_year(date(2024, 2, 29)) == date(2023, 2, 28)


def test_preset_current_year_to_date() -> None:
    s, e = resolve_income_expense_preset("current_year_to_date", date(2026, 5, 6))
    assert s == date(2026, 1, 1)
    assert e == date(2026, 5, 6)


def test_preset_prior_full_year() -> None:
    s, e = resolve_income_expense_preset("prior_full_year", date(2026, 5, 6))
    assert s == date(2025, 1, 1)
    assert e == date(2025, 12, 31)


def test_preset_prior_year_to_date() -> None:
    s, e = resolve_income_expense_preset("prior_year_to_date", date(2026, 5, 6))
    assert s == date(2025, 1, 1)
    assert e == date(2025, 5, 6)


def test_natural_pl_signs() -> None:
    # Credit to revenue (raw negative) -> positive revenue
    assert natural_pl_total_for_account_type("revenue", Decimal("-100")) == Decimal("100")
    # Debit to expense (raw positive) -> positive expense
    assert natural_pl_total_for_account_type("expense", Decimal("40")) == Decimal("40")


def test_income_expense_report_rejects_inverted_range() -> None:
    service = LedgerService(connection_factory=_connection_should_not_open)
    with pytest.raises(LedgerValidationError, match="end_date"):
        service.income_expense_report(
            start_date=date(2026, 5, 1),
            end_date=date(2026, 4, 1),
            exclude_zero_balance_accounts=False,
        )


def _sample_report() -> IncomeExpenseReportOut:
    return IncomeExpenseReportOut(
        period=IncomeExpensePeriodEcho(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)),
        currency_label="single_currency_numeric_18_2",
        preset=None,
        exclude_zero_balance_accounts=False,
        revenue_accounts=[
            IncomeExpenseAccountRowOut(
                account_id=1,
                account_name="Rent",
                account_type="revenue",
                is_active=True,
                amount=Decimal("1000.00"),
            ),
        ],
        expense_accounts=[
            IncomeExpenseAccountRowOut(
                account_id=2,
                account_name="Repairs",
                account_type="expense",
                is_active=True,
                amount=Decimal("250.50"),
            ),
        ],
        total_revenue=Decimal("1000.00"),
        total_expense=Decimal("250.50"),
        net_income=Decimal("749.50"),
    )


def test_income_expense_csv_row_order_and_subtotals() -> None:
    raw = income_expense_report_csv_bytes(_sample_report()).decode("utf-8")
    rows = list(csv.reader(io.StringIO(raw)))
    fields = [r[0] for r in rows[1:] if r and r[0]]
    rev_acc = fields.index("revenue")
    rev_sub = fields.index("revenue_subtotal")
    exp_acc = fields.index("expense")
    exp_sub = fields.index("expense_subtotal")
    net = fields.index("net_income")
    assert rev_acc < rev_sub < exp_acc < exp_sub < net
    assert fields[-1] == "net_income"
    assert "currency_label" not in fields
    by_key = {r[0]: r for r in rows[1:] if r and len(r) >= 3}
    assert by_key["revenue_subtotal"][2] == "1000.00"
    assert by_key["expense_subtotal"][2] == "250.50"
    assert by_key["net_income"][2] == "749.50"


def test_income_expense_pdf_contains_subtotals_and_currency_amounts() -> None:
    try:
        resolve_pdf_unicode_font_path()
    except RuntimeError as exc:
        pytest.skip(f"Unicode PDF font not available: {exc}")
    pdf_bytes = income_expense_report_pdf_bytes(_sample_report())
    assert pdf_bytes[:4] == b"%PDF"
    text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    assert "Revenue subtotal" in text
    assert "Expense subtotal" in text
    assert "Net income" in text
    assert "1,000.00" in text
    assert "250.50" in text
    assert "749.50" in text
    assert "Currency:" not in text
