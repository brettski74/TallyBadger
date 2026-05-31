"""Read-only journal entry settlement preview (#221)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from tallybadger.ledger.models import (
    AccrualObligationOut,
    AccountOut,
    JournalEntrySettlementPreviewOut,
    JournalEntryWrite,
    JournalLineIn,
    SettlementPreviewAllocationOut,
    SettlementType,
)
from tallybadger.ledger.settlement_utils import fifo_allocate, receipt_bridge_account_id

_CASH_SIDE_ACCOUNT_TYPES = frozenset({"asset", "liability"})


@dataclass(frozen=True)
class _PathMatch:
    settlement_type: SettlementType
    pl_account_id: int
    cash_amount: Decimal
    pl_line_indices: tuple[int, ...]


def _line_belongs_to_party(line: JournalLineIn, party_id: int) -> bool:
    return line.party_id is None or line.party_id == party_id


def _detect_receipt_path(
    lines: list[JournalLineIn],
    *,
    party_id: int,
    accounts_by_id: dict[int, AccountOut],
    allow_mixed_cash_signs: bool = False,
) -> _PathMatch | None:
    revenue_accounts: set[int] = set()
    revenue_line_indices: list[int] = []
    cash_debit_total = Decimal("0")
    has_cash_credit = False

    for index, line in enumerate(lines):
        account = accounts_by_id.get(line.account_id)
        if account is None or not _line_belongs_to_party(line, party_id):
            continue
        if account.type == "revenue" and line.amount < Decimal("0"):
            revenue_accounts.add(line.account_id)
            revenue_line_indices.append(index)
        elif account.type in _CASH_SIDE_ACCOUNT_TYPES:
            if line.amount > Decimal("0"):
                cash_debit_total += line.amount
            elif line.amount < Decimal("0"):
                has_cash_credit = True

    if not revenue_accounts or len(revenue_accounts) != 1:
        return None
    if not allow_mixed_cash_signs and has_cash_credit:
        return None
    if cash_debit_total <= Decimal("0"):
        return None

    return _PathMatch(
        settlement_type="receipt",
        pl_account_id=next(iter(revenue_accounts)),
        cash_amount=cash_debit_total,
        pl_line_indices=tuple(revenue_line_indices),
    )


def _detect_payment_path(
    lines: list[JournalLineIn],
    *,
    party_id: int,
    accounts_by_id: dict[int, AccountOut],
    allow_mixed_cash_signs: bool = False,
) -> _PathMatch | None:
    expense_accounts: set[int] = set()
    expense_line_indices: list[int] = []
    cash_credit_total = Decimal("0")
    has_cash_debit = False

    for index, line in enumerate(lines):
        account = accounts_by_id.get(line.account_id)
        if account is None or not _line_belongs_to_party(line, party_id):
            continue
        if account.type == "expense" and line.amount > Decimal("0"):
            expense_accounts.add(line.account_id)
            expense_line_indices.append(index)
        elif account.type in _CASH_SIDE_ACCOUNT_TYPES:
            if line.amount < Decimal("0"):
                cash_credit_total += -line.amount
            elif line.amount > Decimal("0"):
                has_cash_debit = True

    if not expense_accounts or len(expense_accounts) != 1:
        return None
    if not allow_mixed_cash_signs and has_cash_debit:
        return None
    if cash_credit_total <= Decimal("0"):
        return None

    return _PathMatch(
        settlement_type="payment",
        pl_account_id=next(iter(expense_accounts)),
        cash_amount=cash_credit_total,
        pl_line_indices=tuple(expense_line_indices),
    )


def _proposal_lines_for_path(
    path: _PathMatch,
    *,
    entry_date: date,
    party_id: int,
    bridge_account_id: int | None,
    accounts_receivable_account_id: int | None,
    unearned_revenue_account_id: int | None,
    obligations: list[AccrualObligationOut],
    original_lines: list[JournalLineIn],
) -> tuple[list[JournalLineIn], list[SettlementPreviewAllocationOut]] | None:
    allocations_pairs, remainder = fifo_allocate(obligations, path.cash_amount)
    if not allocations_pairs:
        return None

    obligation_by_id = {obligation.id: obligation for obligation in obligations}
    allocation_out: list[SettlementPreviewAllocationOut] = []
    proposal_lines: list[JournalLineIn] = []
    sample_line = original_lines[path.pl_line_indices[0]]

    for obligation_id, applied in allocations_pairs:
        obligation = obligation_by_id[obligation_id]
        if path.settlement_type == "receipt":
            receipt_bridge_id = receipt_bridge_account_id(
                entry_date,
                obligation.source_entry_date,
                accounts_receivable_account_id=accounts_receivable_account_id,
                unearned_revenue_account_id=unearned_revenue_account_id,
            )
            if receipt_bridge_id is None:
                return None
            proposal_lines.append(
                JournalLineIn(
                    account_id=receipt_bridge_id,
                    party_id=party_id,
                    amount=-applied,
                    obligation_id=obligation_id,
                ),
            )
        else:
            if bridge_account_id is None:
                return None
            proposal_lines.append(
                JournalLineIn(
                    account_id=bridge_account_id,
                    party_id=party_id,
                    amount=applied,
                    obligation_id=obligation_id,
                ),
            )
        allocation_out.append(
            SettlementPreviewAllocationOut(
                obligation_id=obligation_id,
                accrual_date=obligation.source_entry_date,
                source_entry_summary=obligation.source_entry_summary,
                open_amount=obligation.open_amount,
                applied_amount=applied,
                settlement_type=path.settlement_type,
            ),
        )

    if remainder > Decimal("0"):
        party_on_line = sample_line.party_id if sample_line.party_id is not None else party_id
        if path.settlement_type == "receipt":
            proposal_lines.append(
                JournalLineIn(
                    account_id=path.pl_account_id,
                    party_id=party_on_line,
                    amount=-remainder,
                    obligation_id=None,
                ),
            )
        else:
            proposal_lines.append(
                JournalLineIn(
                    account_id=path.pl_account_id,
                    party_id=party_on_line,
                    amount=remainder,
                    obligation_id=None,
                ),
            )

    return proposal_lines, allocation_out


def build_journal_entry_settlement_preview(
    payload: JournalEntryWrite,
    *,
    party_id: int,
    party_name: str,
    accounts_by_id: dict[int, AccountOut],
    accounts_receivable_account_id: int | None,
    accounts_payable_account_id: int | None,
    unearned_revenue_account_id: int | None,
    list_obligations: Callable[
        [int, int, Literal["receivable", "payable"]],
        list[AccrualObligationOut],
    ],
) -> JournalEntrySettlementPreviewOut | None:
    """Return a settlement preview offer, or ``None`` when the gate fails or no obligations match."""
    if any(line.obligation_id is not None for line in payload.lines):
        return None

    party_ids = {line.party_id for line in payload.lines if line.party_id is not None}
    if len(party_ids) != 1 or party_id not in party_ids:
        return None

    receipt_relaxed = _detect_receipt_path(
        payload.lines,
        party_id=party_id,
        accounts_by_id=accounts_by_id,
        allow_mixed_cash_signs=True,
    )
    payment_relaxed = _detect_payment_path(
        payload.lines,
        party_id=party_id,
        accounts_by_id=accounts_by_id,
        allow_mixed_cash_signs=True,
    )
    if receipt_relaxed is not None and payment_relaxed is not None:
        receipt_path = receipt_relaxed
        payment_path = payment_relaxed
    else:
        receipt_path = _detect_receipt_path(
            payload.lines,
            party_id=party_id,
            accounts_by_id=accounts_by_id,
            allow_mixed_cash_signs=False,
        )
        payment_path = _detect_payment_path(
            payload.lines,
            party_id=party_id,
            accounts_by_id=accounts_by_id,
            allow_mixed_cash_signs=False,
        )

    if receipt_path is None and payment_path is None:
        return None

    replaced_indices: set[int] = set()
    path_proposal_lines: list[JournalLineIn] = []
    combined_allocations: list[SettlementPreviewAllocationOut] = []
    receipt_cash_amount: Decimal | None = None
    payment_cash_amount: Decimal | None = None

    path_specs: list[tuple[_PathMatch, int | None, Literal["receivable", "payable"]]] = []
    if receipt_path is not None:
        path_specs.append((receipt_path, accounts_receivable_account_id, "receivable"))
    if payment_path is not None:
        path_specs.append((payment_path, accounts_payable_account_id, "payable"))

    for path, bridge_id, obligation_type in path_specs:
        if bridge_id is None:
            return None
        obligations = list_obligations(party_id, path.pl_account_id, obligation_type)
        proposal = _proposal_lines_for_path(
            path,
            entry_date=payload.entry_date,
            party_id=party_id,
            bridge_account_id=bridge_id,
            accounts_receivable_account_id=accounts_receivable_account_id,
            unearned_revenue_account_id=unearned_revenue_account_id,
            obligations=obligations,
            original_lines=payload.lines,
        )
        if proposal is None:
            continue
        lines, allocations = proposal
        replaced_indices.update(path.pl_line_indices)
        path_proposal_lines.extend(lines)
        combined_allocations.extend(allocations)
        if path.settlement_type == "receipt":
            receipt_cash_amount = path.cash_amount
        else:
            payment_cash_amount = path.cash_amount

    if not combined_allocations:
        return None

    kept_lines = [
        JournalLineIn(
            account_id=line.account_id,
            party_id=line.party_id,
            amount=line.amount,
            obligation_id=None,
        )
        for index, line in enumerate(payload.lines)
        if index not in replaced_indices
    ]
    proposed_lines = kept_lines + path_proposal_lines
    if sum(line.amount for line in proposed_lines) != Decimal("0"):
        return None

    return JournalEntrySettlementPreviewOut(
        party_id=party_id,
        party_name=party_name,
        lines=proposed_lines,
        allocations=combined_allocations,
        receipt_cash_amount=receipt_cash_amount,
        payment_cash_amount=payment_cash_amount,
    )
