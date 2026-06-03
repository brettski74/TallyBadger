"""Shared settlement allocation helpers (#152, #221)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from tallybadger.ledger.models import AccrualDirection, AccrualObligationOut


def accrual_plan_bridge_account_id(
    direction: AccrualDirection,
    *,
    accounts_receivable_account_id: int | None,
    accounts_payable_account_id: int | None,
) -> int | None:
    """A/R for revenue plans; A/P for expense plans (#235)."""
    if direction == "revenue":
        return accounts_receivable_account_id
    return accounts_payable_account_id


def is_early_receipt_obligation(
    event_date: date,
    source_entry_date: date | None,
) -> bool:
    """True when cash is received before the accrual journal entry date."""
    return source_entry_date is not None and source_entry_date > event_date


def receipt_bridge_account_id(
    event_date: date,
    source_entry_date: date | None,
    *,
    accounts_receivable_account_id: int | None,
    unearned_revenue_account_id: int | None,
) -> int | None:
    """A/R for due receipts; unearned revenue when the obligation accrual is still in the future."""
    if is_early_receipt_obligation(event_date, source_entry_date):
        return unearned_revenue_account_id
    return accounts_receivable_account_id


def is_early_payment_obligation(
    event_date: date,
    source_entry_date: date | None,
) -> bool:
    """True when cash is paid before the accrual journal entry date."""
    return source_entry_date is not None and source_entry_date > event_date


def payment_bridge_account_id(
    event_date: date,
    source_entry_date: date | None,
    *,
    accounts_payable_account_id: int | None,
    prepaid_expenses_account_id: int | None,
) -> int | None:
    """A/P for due payments; prepaid expenses when the obligation accrual is still in the future."""
    if is_early_payment_obligation(event_date, source_entry_date):
        return prepaid_expenses_account_id
    return accounts_payable_account_id


def fifo_allocate(
    obligations: list[AccrualObligationOut],
    total: Decimal,
) -> tuple[list[tuple[int, Decimal]], Decimal]:
    """Allocate ``total`` across open obligations in FIFO order (date, then id)."""
    remaining = total
    allocations: list[tuple[int, Decimal]] = []
    for obligation in obligations:
        if remaining <= Decimal("0"):
            break
        open_amt = obligation.open_amount
        if open_amt <= Decimal("0"):
            continue
        alloc = min(open_amt, remaining)
        allocations.append((obligation.id, alloc))
        remaining -= alloc
    return allocations, remaining
