"""Shared settlement allocation helpers (#152, #221)."""

from __future__ import annotations

from decimal import Decimal

from tallybadger.ledger.models import AccrualObligationOut


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
