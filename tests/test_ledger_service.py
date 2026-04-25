from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from tallybadger.ledger.models import JournalEntryWrite, JournalLineIn
from tallybadger.ledger.service import LedgerService, LedgerValidationError


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


def test_create_entry_runs_inside_transaction() -> None:
    service, conn, cur = _build_service_with_mocks()
    cur.fetchone.side_effect = [{"id": 42}, {"line_count": 2, "total": Decimal("0")}]
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
    cur.fetchone.return_value = {"line_count": 2, "total": Decimal("0")}
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
