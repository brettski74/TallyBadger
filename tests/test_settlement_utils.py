from datetime import date

from tallybadger.ledger.settlement_utils import (
    is_early_payment_obligation,
    is_early_receipt_obligation,
    payment_bridge_account_id,
    receipt_bridge_account_id,
)


def test_is_early_receipt_obligation() -> None:
    assert is_early_receipt_obligation(date(2026, 6, 26), date(2026, 7, 1)) is True
    assert is_early_receipt_obligation(date(2026, 7, 1), date(2026, 7, 1)) is False
    assert is_early_receipt_obligation(date(2026, 7, 1), None) is False


def test_is_early_payment_obligation() -> None:
    assert is_early_payment_obligation(date(2026, 7, 26), date(2026, 8, 1)) is True
    assert is_early_payment_obligation(date(2026, 8, 1), date(2026, 8, 1)) is False
    assert is_early_payment_obligation(date(2026, 8, 1), None) is False


def test_receipt_bridge_account_id() -> None:
    assert (
        receipt_bridge_account_id(
            date(2026, 6, 26),
            date(2026, 7, 1),
            accounts_receivable_account_id=10,
            unearned_revenue_account_id=20,
        )
        == 20
    )
    assert (
        receipt_bridge_account_id(
            date(2026, 7, 1),
            date(2026, 7, 1),
            accounts_receivable_account_id=10,
            unearned_revenue_account_id=20,
        )
        == 10
    )


def test_payment_bridge_account_id() -> None:
    assert (
        payment_bridge_account_id(
            date(2026, 7, 26),
            date(2026, 8, 1),
            accounts_payable_account_id=30,
            prepaid_expenses_account_id=40,
        )
        == 40
    )
    assert (
        payment_bridge_account_id(
            date(2026, 8, 1),
            date(2026, 8, 1),
            accounts_payable_account_id=30,
            prepaid_expenses_account_id=40,
        )
        == 30
    )
