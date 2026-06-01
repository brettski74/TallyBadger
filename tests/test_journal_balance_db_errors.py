"""Unit tests for mapping journal balance constraint trigger failures (#244)."""

import pytest
from psycopg import errors as pg_errors

from tallybadger.ledger.service import (
    LedgerValidationError,
    _journal_balance_db_error_message,
    _reraise_journal_balance_db_error,
)


def test_journal_balance_db_error_message_recognises_trigger_text() -> None:
    exc = pg_errors.RaiseException(
        "journal entry is not balanced (entry_id=3, sum=1.00)"
    )
    assert _journal_balance_db_error_message(exc) == str(exc).strip()


def test_journal_balance_db_error_message_ignores_unrelated_raise() -> None:
    exc = pg_errors.RaiseException("some other rule")
    assert _journal_balance_db_error_message(exc) is None


def test_reraise_journal_balance_db_error_maps_to_ledger_validation() -> None:
    exc = pg_errors.RaiseException(
        "journal entry requires at least two lines (entry_id=9, line_count=0)"
    )
    with pytest.raises(LedgerValidationError, match="journal entry requires at least two lines"):
        _reraise_journal_balance_db_error(exc)


def test_reraise_journal_balance_db_error_reraises_unknown_raise() -> None:
    exc = pg_errors.RaiseException("unrelated")
    with pytest.raises(pg_errors.RaiseException, match="unrelated"):
        _reraise_journal_balance_db_error(exc)
