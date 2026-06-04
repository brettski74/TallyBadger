"""Unit tests for account statement validation and export serialization."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import io

import pytest
from pypdf import PdfReader

from tallybadger.api.account_statement_export import (
    account_statement_report_csv_bytes,
    account_statement_report_filename_stem,
    account_statement_report_pdf_bytes,
)
from tallybadger.ledger.account_statement_report import (
    BALANCE_FORWARD_SUMMARY,
    CLOSING_BALANCE_SUMMARY,
    AccountStatementValidationError,
    build_account_statement_report,
)
from tallybadger.ledger.models import (
    AccountStatementAccountEcho,
    AccountStatementPeriodEcho,
    AccountStatementReportOut,
    AccountStatementRowOut,
)
from tallybadger.ledger.service import LedgerService, LedgerValidationError


@contextmanager
def _connection_should_not_open():
    raise AssertionError("database should not open for this validation-only path")
    yield  # pragma: no cover


def _sample_report() -> AccountStatementReportOut:
    return AccountStatementReportOut(
        account=AccountStatementAccountEcho(account_id=1, account_name="Cash", is_active=True),
        period=AccountStatementPeriodEcho(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31)),
        currency_label="single_currency_numeric_18_2",
        balance_forward=Decimal("100.00"),
        closing_balance=Decimal("150.00"),
        rows=[
            AccountStatementRowOut(
                row_kind="balance_forward",
                entry_date=date(2026, 5, 1),
                summary=BALANCE_FORWARD_SUMMARY,
                balance=Decimal("100.00"),
            ),
            AccountStatementRowOut(
                row_kind="activity",
                entry_date=date(2026, 5, 10),
                summary="deposit",
                counterparty_account="Revenue",
                party="-- None --",
                debit=Decimal("50.00"),
                balance=Decimal("150.00"),
                entry_id=10,
            ),
            AccountStatementRowOut(
                row_kind="closing_balance",
                entry_date=date(2026, 5, 31),
                summary=CLOSING_BALANCE_SUMMARY,
                balance=Decimal("150.00"),
            ),
        ],
    )


def test_account_statement_report_rejects_inverted_range() -> None:
    service = LedgerService(connection_factory=_connection_should_not_open)
    with pytest.raises(LedgerValidationError, match="end_date"):
        service.account_statement_report(
            account_id=1,
            start_date=date(2026, 5, 31),
            end_date=date(2026, 5, 1),
        )


def test_build_account_statement_rejects_inverted_range() -> None:
    class _FakeCursor:
        def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return None

        def fetchone(self):
            return {"id": 1, "name": "Cash", "is_active": True}

    with pytest.raises(AccountStatementValidationError, match="end_date"):
        build_account_statement_report(
            _FakeCursor(),
            account_id=1,
            start_date=date(2026, 5, 31),
            end_date=date(2026, 5, 1),
        )


def test_account_statement_filename_stem_includes_account_and_dates() -> None:
    stem = account_statement_report_filename_stem(_sample_report())
    assert stem == "account-statement_Cash_2026-05-01_2026-05-31"


def test_account_statement_csv_includes_special_rows_and_columns() -> None:
    raw = account_statement_report_csv_bytes(_sample_report()).decode("utf-8")
    lines = raw.strip().splitlines()
    assert lines[0].startswith("entry_date,summary,account")
    assert any(BALANCE_FORWARD_SUMMARY in line for line in lines)
    assert any(CLOSING_BALANCE_SUMMARY in line for line in lines)
    assert any(",deposit,Revenue," in line for line in lines)


def test_account_statement_activity_row_zero_net_has_empty_debit_credit() -> None:
    report = AccountStatementReportOut(
        account=AccountStatementAccountEcho(account_id=1, account_name="Cash", is_active=True),
        period=AccountStatementPeriodEcho(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31)),
        currency_label="single_currency_numeric_18_2",
        balance_forward=Decimal("0"),
        closing_balance=Decimal("0"),
        rows=[
            AccountStatementRowOut(
                row_kind="balance_forward",
                entry_date=date(2026, 5, 1),
                summary=BALANCE_FORWARD_SUMMARY,
                balance=Decimal("0"),
            ),
            AccountStatementRowOut(
                row_kind="activity",
                entry_date=date(2026, 5, 2),
                summary="wash",
                counterparty_account="Petty Cash",
                party="-- None --",
                debit=None,
                credit=None,
                balance=Decimal("0"),
                entry_id=2,
            ),
            AccountStatementRowOut(
                row_kind="closing_balance",
                entry_date=date(2026, 5, 31),
                summary=CLOSING_BALANCE_SUMMARY,
                balance=Decimal("0"),
            ),
        ],
    )
    activity = next(r for r in report.rows if r.row_kind == "activity")
    assert activity.debit is None
    assert activity.credit is None


def test_account_statement_pdf_contains_title_and_amounts() -> None:
    pdf_bytes = account_statement_report_pdf_bytes(_sample_report())
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Cash Statement" in text
    assert BALANCE_FORWARD_SUMMARY in text
    assert "$150.00" in text
