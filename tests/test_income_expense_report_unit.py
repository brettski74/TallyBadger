"""Unit tests for Income & Expense preset resolution and P&L sign mapping."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest

from tallybadger.ledger.income_expense_report import (
    natural_pl_total_for_account_type,
    resolve_income_expense_preset,
    same_calendar_day_prior_year,
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
