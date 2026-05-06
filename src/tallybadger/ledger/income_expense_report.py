"""Income & expense (P&L-style) reporting: period presets and natural P&L amount mapping.

Ledger convention: journal line ``amount`` is **positive = debit**, **negative = credit**.

Natural presentation for this report (positive operating figures):

- **Revenue** accounts (credit-normal): ``reported = -sum(raw_line_amounts)`` for lines in period.
- **Expense** accounts (debit-normal): ``reported = sum(raw_line_amounts)`` for lines in period.

Only ``revenue`` and ``expense`` account types are included. Journal entries are not filtered by
``requires_review`` — the same posted lines appear here as in unrestricted journal browsing
(``needs_review`` not set on ``/journal-entries``).
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Literal

IncomeExpensePreset = Literal["current_year_to_date", "prior_full_year", "prior_year_to_date"]

INCOME_EXPENSE_CURRENCY_LABEL = "single_currency_numeric_18_2"


def same_calendar_day_prior_year(as_of: date) -> date:
    """``as_of`` translated to the prior calendar year, preserving month/day when valid."""
    y = as_of.year - 1
    try:
        return date(y, as_of.month, as_of.day)
    except ValueError:
        last = calendar.monthrange(y, as_of.month)[1]
        return date(y, as_of.month, last)


def resolve_income_expense_preset(
    preset: IncomeExpensePreset,
    as_of: date,
) -> tuple[date, date]:
    """Resolve a preset to inclusive ``(start_date, end_date)`` (financial year = calendar year)."""
    if preset == "current_year_to_date":
        start = date(as_of.year, 1, 1)
        end = as_of if as_of >= start else start
        return start, end
    if preset == "prior_full_year":
        y = as_of.year - 1
        return date(y, 1, 1), date(y, 12, 31)
    if preset == "prior_year_to_date":
        start = date(as_of.year - 1, 1, 1)
        end = same_calendar_day_prior_year(as_of)
        if end < start:
            end = start
        return start, end
    raise ValueError(f"unknown preset: {preset!r}")


def natural_pl_total_for_account_type(account_type: str, raw_sum: Decimal) -> Decimal:
    """Map SQL aggregate of raw line amounts to natural P&L sign for the account type."""
    if account_type == "revenue":
        return -raw_sum
    if account_type == "expense":
        return raw_sum
    raise ValueError(f"not a P&L account type: {account_type!r}")
