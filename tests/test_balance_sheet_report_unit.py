"""Unit tests for Balance Sheet helper and export formatting."""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from tallybadger.api.balance_sheet_export import (
    balance_sheet_report_csv_bytes,
    balance_sheet_report_pdf_bytes,
)
from tallybadger.api.income_expense_export import resolve_pdf_unicode_font_path
from tallybadger.ledger.balance_sheet_report import (
    natural_balance_sheet_total_for_account_type,
    resolve_balance_sheet_preset,
)
from tallybadger.ledger.models import (
    BalanceSheetAccountRowOut,
    BalanceSheetBalanceCheckOut,
    BalanceSheetPeriodEcho,
    BalanceSheetReportOut,
    BalanceSheetSectionOut,
)


def test_balance_sheet_preset_prior_year_end() -> None:
    assert resolve_balance_sheet_preset("prior_year_end", date(2026, 5, 6)) == date(2025, 12, 31)


def test_natural_balance_sheet_signs() -> None:
    assert natural_balance_sheet_total_for_account_type("asset", Decimal("10")) == Decimal("10")
    assert natural_balance_sheet_total_for_account_type("liability", Decimal("-22")) == Decimal("22")
    assert natural_balance_sheet_total_for_account_type("equity", Decimal("-7.5")) == Decimal("7.5")


def _sample_report() -> BalanceSheetReportOut:
    return BalanceSheetReportOut(
        period=BalanceSheetPeriodEcho(as_of_date=date(2026, 1, 31)),
        currency_label="single_currency_numeric_18_2",
        preset="today",
        exclude_requires_review=False,
        assets=BalanceSheetSectionOut(
            section="assets",
            label="Assets",
            accounts=[
                BalanceSheetAccountRowOut(
                    account_id=1,
                    account_name="Cash",
                    account_type="asset",
                    is_active=True,
                    amount=Decimal("1450.00"),
                )
            ],
            total=Decimal("1450.00"),
        ),
        liabilities=BalanceSheetSectionOut(
            section="liabilities",
            label="Liabilities",
            accounts=[
                BalanceSheetAccountRowOut(
                    account_id=2,
                    account_name="Loan",
                    account_type="liability",
                    is_active=True,
                    amount=Decimal("200.00"),
                )
            ],
            total=Decimal("200.00"),
        ),
        equity=BalanceSheetSectionOut(
            section="equity",
            label="Equity",
            accounts=[
                BalanceSheetAccountRowOut(
                    account_id=3,
                    account_name="Owner Contributions",
                    account_type="equity",
                    is_active=True,
                    amount=Decimal("1000.00"),
                ),
                BalanceSheetAccountRowOut(
                    account_id=None,
                    account_name="Retained Earnings",
                    account_type="computed_equity",
                    is_active=None,
                    is_computed=True,
                    amount=Decimal("250.00"),
                ),
            ],
            total=Decimal("1250.00"),
        ),
        balance_check=BalanceSheetBalanceCheckOut(
            assets_total=Decimal("1450.00"),
            liabilities_total=Decimal("200.00"),
            equity_total=Decimal("1250.00"),
            liabilities_plus_equity=Decimal("1450.00"),
            is_balanced=True,
            difference=Decimal("0.00"),
        ),
    )


def test_balance_sheet_csv_has_section_totals_and_computed_equity_row() -> None:
    raw = balance_sheet_report_csv_bytes(_sample_report()).decode("utf-8")
    rows = list(csv.reader(io.StringIO(raw)))
    fields = [r[0] for r in rows[1:] if r and r[0]]
    assert fields.index("asset") < fields.index("assets_total")
    assert fields.index("liability") < fields.index("liabilities_total")
    assert fields.index("equity_computed") < fields.index("equity_total")
    by_key = {r[0]: r for r in rows[1:] if r and len(r) >= 3}
    assert by_key["equity_computed"][1] == "Retained Earnings"
    assert by_key["liabilities_plus_equity"][2] == "1450.00"
    assert by_key["is_balanced"][2] == "true"


def test_balance_sheet_pdf_contains_key_labels_and_amounts() -> None:
    try:
        resolve_pdf_unicode_font_path()
    except RuntimeError as exc:
        pytest.skip(f"Unicode PDF font not available: {exc}")
    pdf_bytes = balance_sheet_report_pdf_bytes(_sample_report())
    assert pdf_bytes[:4] == b"%PDF"
    text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    assert "Balance Sheet" in text
    assert "Retained Earnings" in text
    assert "Balance check" in text
    assert "Liabilities + equity" in text
    assert "Balance" in text
    assert "Difference" not in text
    assert "1,450.00" in text
