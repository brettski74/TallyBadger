"""Balance Sheet reporting helpers: presets and natural account sign mapping."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

BalanceSheetPreset = Literal["today", "prior_year_end"]

BALANCE_SHEET_CURRENCY_LABEL = "single_currency_numeric_18_2"


def resolve_balance_sheet_preset(preset: BalanceSheetPreset, as_of: date) -> date:
    """Resolve a preset to an as-of date."""
    if preset == "today":
        return as_of
    if preset == "prior_year_end":
        return date(as_of.year - 1, 12, 31)
    raise ValueError(f"unknown preset: {preset!r}")


def natural_balance_sheet_total_for_account_type(account_type: str, raw_sum: Decimal) -> Decimal:
    """Map raw ledger sums to natural positive figures for balance sheet display."""
    if account_type == "asset":
        return raw_sum
    if account_type in ("liability", "equity"):
        return -raw_sum
    raise ValueError(f"not a balance-sheet account type: {account_type!r}")
