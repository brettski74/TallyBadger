from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from tallybadger.ledger.models import (
    AccrualPlanCreate,
    JournalEntryWrite,
    JournalLineIn,
)
from tallybadger.ledger.service import (
    JOURNAL_LIST_SPLIT_LABEL,
    LedgerService,
    LedgerValidationError,
    labels_and_amount_for_journal_list_lines,
)


def _build_service_with_mocks() -> tuple[LedgerService, MagicMock, MagicMock]:
    conn = MagicMock()
    txn_cm = MagicMock()
    txn_cm.__enter__.return_value = None
    txn_cm.__exit__.return_value = None
    conn.transaction.return_value = txn_cm

    cursor_cm = MagicMock()
    cur = MagicMock()
    cursor_cm.__enter__.return_value = cur
    cursor_cm.__exit__.return_value = None
    conn.cursor.return_value = cursor_cm

    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = conn
    conn_cm.__exit__.return_value = None

    service = LedgerService(connection_factory=lambda: conn_cm)
    return service, conn, cur


def test_validate_lines_requires_balance_and_non_zero() -> None:
    with pytest.raises(LedgerValidationError):
        LedgerService._validate_lines([JournalLineIn(account_id=1, amount=Decimal("0"))])

    with pytest.raises(LedgerValidationError):
        LedgerService._validate_lines(
            [
                JournalLineIn(account_id=1, amount=Decimal("10")),
                JournalLineIn(account_id=2, amount=Decimal("-9")),
            ]
        )

    LedgerService._validate_lines(
        [
            JournalLineIn(account_id=1, amount=Decimal("10")),
            JournalLineIn(account_id=2, amount=Decimal("-10")),
        ]
    )


def test_validate_summary_requires_non_blank_text() -> None:
    with pytest.raises(LedgerValidationError, match="summary is required"):
        LedgerService._validate_summary("   ")

    LedgerService._validate_summary("rent accrual")


def test_create_entry_runs_inside_transaction() -> None:
    service, conn, cur = _build_service_with_mocks()
    cur.fetchall.return_value = [{"id": 1}, {"id": 2}]
    cur.fetchone.side_effect = [
        {"id": 42},
        {"is_active": True},
        {"is_active": True},
        {"line_count": 2, "total": Decimal("0")},
    ]
    service.get_entry = MagicMock(  # type: ignore[method-assign]
        return_value={
            "id": 42,
            "entry_date": date(2026, 4, 24),
            "description": "rent",
            "created_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
            "lines": [],
        }
    )

    payload = JournalEntryWrite(
        entry_date=date(2026, 4, 24),
        summary="rent",
        description="rent",
        lines=[
            JournalLineIn(account_id=1, amount=Decimal("1000.00")),
            JournalLineIn(account_id=2, amount=Decimal("-1000.00")),
        ],
    )
    service.create_entry(payload)

    conn.transaction.assert_called_once()


def test_update_entry_runs_inside_transaction() -> None:
    service, conn, cur = _build_service_with_mocks()
    cur.rowcount = 1
    cur.fetchall.side_effect = [
        [{"id": 1}, {"id": 2}],
        [
            {"account_id": 1, "party_id": None},
            {"account_id": 2, "party_id": None},
        ],
    ]
    cur.fetchone.side_effect = [
        {"c": 0},
        {"cheque_id": None},
        {"line_count": 2, "total": Decimal("0")},
    ]
    service.get_entry = MagicMock(  # type: ignore[method-assign]
        return_value={
            "id": 7,
            "entry_date": date(2026, 4, 24),
            "description": "update",
            "created_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
            "lines": [],
        }
    )

    payload = JournalEntryWrite(
        entry_date=date(2026, 4, 24),
        summary="update",
        description="update",
        lines=[
            JournalLineIn(account_id=1, amount=Decimal("50")),
            JournalLineIn(account_id=2, amount=Decimal("-50")),
        ],
    )
    service.update_entry(7, payload)

    conn.transaction.assert_called_once()


def test_delete_entry_runs_inside_transaction() -> None:
    service, conn, cur = _build_service_with_mocks()
    cur.rowcount = 1

    service.delete_entry(5)

    conn.transaction.assert_called_once()


def test_journal_list_labels_single_debit_and_credit() -> None:
    d, c, amt = labels_and_amount_for_journal_list_lines(
        [
            (Decimal("10.00"), "Cash"),
            (Decimal("-10.00"), "Rent"),
        ]
    )
    assert d == "Cash"
    assert c == "Rent"
    assert amt == Decimal("10.00")


def test_journal_list_labels_split_debit() -> None:
    d, c, amt = labels_and_amount_for_journal_list_lines(
        [
            (Decimal("30.00"), "Cash"),
            (Decimal("70.00"), "Escrow"),
            (Decimal("-100.00"), "Due To"),
        ]
    )
    assert d == JOURNAL_LIST_SPLIT_LABEL
    assert c == "Due To"
    assert amt == Decimal("100.00")


def test_journal_list_labels_split_credit() -> None:
    d, c, amt = labels_and_amount_for_journal_list_lines(
        [
            (Decimal("200.00"), "Bank"),
            (Decimal("-120.00"), "Repairs"),
            (Decimal("-80.00"), "Fees"),
        ]
    )
    assert d == "Bank"
    assert c == JOURNAL_LIST_SPLIT_LABEL
    assert amt == Decimal("200.00")


def test_journal_list_labels_reject_blank_account_name() -> None:
    with pytest.raises(LedgerValidationError, match="missing account name"):
        labels_and_amount_for_journal_list_lines([(Decimal("1.00"), "   ")])


def test_preview_accrual_plan_monthly_generates_balanced_lines() -> None:
    service, _conn, _cur = _build_service_with_mocks()
    payload = AccrualPlanCreate(
        name="Rent 2026",
        direction="revenue",
        party_id=10,
        target_account_id=2,
        bridge_account_id=1,
        frequency="monthly_day",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        amount=Decimal("100.00"),
        summary_template="{plan} {month}",
        description_template="Generated on {date}",
        day_of_month=1,
    )
    items = service.preview_accrual_plan(payload)
    assert [i.entry_date.isoformat() for i in items] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert items[0].summary == "Rent 2026 2026-01"
    assert sum(line.amount for line in items[0].lines) == Decimal("0")


def test_preview_accrual_plan_monthly_business_day_adjust_rolls_weekend_forward() -> None:
    service, _conn, _cur = _build_service_with_mocks()
    payload = AccrualPlanCreate(
        name="Rent 2026",
        direction="revenue",
        party_id=10,
        target_account_id=2,
        bridge_account_id=1,
        frequency="monthly_day",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        amount=Decimal("100.00"),
        summary_template="{plan} {month}",
        day_of_month=1,
        business_day_adjust=True,
    )
    items = service.preview_accrual_plan(payload)
    assert [i.entry_date.isoformat() for i in items] == ["2026-08-03"]


def test_preview_accrual_plan_yearly_business_day_adjust_rolls_weekend_forward() -> None:
    service, _conn, _cur = _build_service_with_mocks()
    payload = AccrualPlanCreate(
        name="Annual plan",
        direction="expense",
        party_id=10,
        target_account_id=2,
        bridge_account_id=1,
        frequency="yearly",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 31),
        amount=Decimal("100.00"),
        summary_template="{plan} {month}",
        month_of_year=7,
        day_of_month=4,
        business_day_adjust=True,
    )
    items = service.preview_accrual_plan(payload)
    assert [i.entry_date.isoformat() for i in items] == ["2027-07-05"]


def test_weekly_rejects_business_day_adjust() -> None:
    with pytest.raises(ValueError, match="monthly/yearly"):
        AccrualPlanCreate(
            name="Weekly plan",
            direction="revenue",
            party_id=1,
            target_account_id=2,
            bridge_account_id=3,
            frequency="weekly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            amount=Decimal("10.00"),
            summary_template="{plan}",
            day_of_week=0,
            business_day_adjust=True,
        )


def test_expense_plan_target_account_must_be_expense() -> None:
    service, _conn, cur = _build_service_with_mocks()
    cur.fetchall.return_value = [
        {"id": 10, "type": "asset"},
        {"id": 11, "type": "liability"},
    ]
    payload = AccrualPlanCreate(
        name="Expense Plan",
        direction="expense",
        party_id=1,
        target_account_id=10,
        bridge_account_id=11,
        frequency="monthly_day",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        amount=Decimal("50.00"),
        summary_template="{plan}",
        day_of_month=1,
    )
    with pytest.raises(LedgerValidationError, match="type expense"):
        service._assert_plan_account_direction_rules(cur, payload)


def test_settlement_journal_summary_uses_earliest_allocated_accrual() -> None:
    allocation = {1: Decimal("10.00"), 2: Decimal("5.00")}
    obligations = [
        {
            "id": 1,
            "source_entry_id": 10,
            "source_entry_date": date(2026, 2, 1),
            "source_entry_summary": "Feb accrual",
        },
        {
            "id": 2,
            "source_entry_id": 20,
            "source_entry_date": date(2026, 1, 1),
            "source_entry_summary": "Jan accrual",
        },
    ]
    assert (
        LedgerService._settlement_journal_summary(obligations, allocation)
        == "Settlement Jan accrual"
    )


def test_receipt_collapses_only_when_all_allocations_match_accrual_day() -> None:
    allocation = {1: Decimal("1.00"), 2: Decimal("1.00")}
    same = LedgerService._receipt_allocations_all_same_accrual_day(
        [
            {"id": 1, "source_entry_id": 10, "source_line_id": 100, "source_entry_date": date(2026, 7, 1)},
            {"id": 2, "source_entry_id": 20, "source_line_id": 200, "source_entry_date": date(2026, 7, 1)},
        ],
        allocation,
        date(2026, 7, 1),
    )
    assert same is True

    mixed = LedgerService._receipt_allocations_all_same_accrual_day(
        [
            {"id": 1, "source_entry_id": 10, "source_line_id": 100, "source_entry_date": date(2026, 7, 1)},
            {"id": 2, "source_entry_id": 20, "source_line_id": 200, "source_entry_date": date(2026, 6, 1)},
        ],
        allocation,
        date(2026, 7, 1),
    )
    assert mixed is False

    zero_skipped = LedgerService._receipt_allocations_all_same_accrual_day(
        [
            {"id": 1, "source_entry_id": 10, "source_line_id": 100, "source_entry_date": date(2026, 7, 2)},
            {"id": 2, "source_entry_id": 20, "source_line_id": 200, "source_entry_date": date(2026, 7, 1)},
        ],
        {1: Decimal("0"), 2: Decimal("10.00")},
        date(2026, 7, 1),
    )
    assert zero_skipped is True


def test_settlement_journal_summary_tiebreaks_by_entry_id() -> None:
    allocation = {1: Decimal("1.00"), 2: Decimal("1.00")}
    obligations = [
        {
            "id": 1,
            "source_entry_id": 50,
            "source_entry_date": date(2026, 3, 1),
            "source_entry_summary": "Later id",
        },
        {
            "id": 2,
            "source_entry_id": 40,
            "source_entry_date": date(2026, 3, 1),
            "source_entry_summary": "Earlier id",
        },
    ]
    assert (
        LedgerService._settlement_journal_summary(obligations, allocation)
        == "Settlement Earlier id"
    )


def test_split_receipt_allocations_separates_due_and_early() -> None:
    due, early = LedgerService._split_receipt_allocations(
        date(2026, 1, 15),
        [
            {"id": 1, "source_entry_date": date(2026, 1, 1)},
            {"id": 2, "source_entry_date": date(2026, 2, 1)},
        ],
        {1: Decimal("40.00"), 2: Decimal("60.00")},
    )
    assert due == Decimal("40.00")
    assert early == Decimal("60.00")


def test_list_party_subtype_suggestions_reads_dict_rows() -> None:
    service, _conn, cur = _build_service_with_mocks()
    cur.fetchall.return_value = [{"s": "Tenant"}, {"s": "utility"}]

    assert service.list_party_subtype_suggestions() == ["Tenant", "utility"]
