"""Account statement report: balance forward, period activity, closing balance."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from tallybadger.ledger.models import (
    AccountStatementAccountEcho,
    AccountStatementPeriodEcho,
    AccountStatementReportOut,
    AccountStatementRowOut,
)
# Matches ``JOURNAL_LIST_SPLIT_LABEL`` in ``ledger.service`` (avoid import cycle).
_JOURNAL_LIST_SPLIT_LABEL = "-- Split --"


class AccountStatementNotFoundError(Exception):
    """Raised when the statement account id does not exist."""


class AccountStatementValidationError(Exception):
    """Raised when report parameters are invalid."""

ACCOUNT_STATEMENT_CURRENCY_LABEL = "single_currency_numeric_18_2"
ACCOUNT_STATEMENT_PARTY_NONE_LABEL = "-- None --"
ACCOUNT_STATEMENT_PARTY_MULTI_LABEL = "-- Multi --"
BALANCE_FORWARD_SUMMARY = "Balance forward"
CLOSING_BALANCE_SUMMARY = "Closing balance"


def _party_label_from_count(party_count: int, single_name: str | None) -> str:
    if party_count <= 0:
        return ACCOUNT_STATEMENT_PARTY_NONE_LABEL
    if party_count == 1:
        return single_name or ACCOUNT_STATEMENT_PARTY_NONE_LABEL
    return ACCOUNT_STATEMENT_PARTY_MULTI_LABEL


def _counterparty_label(other_count: int, single_name: str | None) -> str:
    if other_count == 1:
        return single_name or _JOURNAL_LIST_SPLIT_LABEL
    return _JOURNAL_LIST_SPLIT_LABEL


def build_account_statement_report(
    cur,
    *,
    account_id: int,
    start_date: date,
    end_date: date,
) -> AccountStatementReportOut:
    """Build an account statement for ``account_id`` over ``[start_date, end_date]`` inclusive."""
    if end_date < start_date:
        raise AccountStatementValidationError("end_date must be on or after start_date")

    cur.execute(
        "SELECT id, name, is_active FROM accounts WHERE id = %s",
        (account_id,),
    )
    account_row = cur.fetchone()
    if account_row is None:
        raise AccountStatementNotFoundError(f"account {account_id} not found")

    cur.execute(
        """
        SELECT COALESCE(SUM(jl.amount), 0) AS balance_forward
        FROM journal_lines jl
        INNER JOIN journal_entries je ON je.id = jl.entry_id
        WHERE jl.account_id = %s AND je.entry_date < %s
        """,
        (account_id, start_date),
    )
    balance_forward = Decimal(cur.fetchone()["balance_forward"])

    cur.execute(
        """
        SELECT je.id AS entry_id,
               je.entry_date,
               je.summary,
               COALESCE(SUM(jl.amount), 0) AS net_amount
        FROM journal_entries je
        INNER JOIN journal_lines jl ON jl.entry_id = je.id AND jl.account_id = %s
        WHERE je.entry_date >= %s AND je.entry_date <= %s
        GROUP BY je.id, je.entry_date, je.summary
        ORDER BY je.entry_date ASC, je.id ASC
        """,
        (account_id, start_date, end_date),
    )
    activity_rows = cur.fetchall()
    entry_ids = [int(r["entry_id"]) for r in activity_rows]

    other_by_entry: dict[int, tuple[int, str | None]] = {}
    party_by_entry: dict[int, tuple[int, str | None]] = {}

    if entry_ids:
        cur.execute(
            """
            SELECT jl.entry_id,
                   COUNT(DISTINCT jl.account_id) AS other_count,
                   MIN(TRIM(a.name)) AS single_name
            FROM journal_lines jl
            INNER JOIN accounts a ON a.id = jl.account_id
            WHERE jl.entry_id = ANY(%s) AND jl.account_id <> %s
            GROUP BY jl.entry_id
            """,
            (entry_ids, account_id),
        )
        for row in cur.fetchall():
            other_by_entry[int(row["entry_id"])] = (
                int(row["other_count"]),
                row["single_name"],
            )

        cur.execute(
            """
            SELECT jl.entry_id,
                   COUNT(DISTINCT p.name) AS party_count,
                   MIN(p.name) AS single_party
            FROM journal_lines jl
            INNER JOIN parties p ON p.id = jl.party_id
            WHERE jl.entry_id = ANY(%s)
            GROUP BY jl.entry_id
            """,
            (entry_ids,),
        )
        for row in cur.fetchall():
            party_by_entry[int(row["entry_id"])] = (
                int(row["party_count"]),
                row["single_party"],
            )

    display_rows: list[AccountStatementRowOut] = []
    display_rows.append(
        AccountStatementRowOut(
            row_kind="balance_forward",
            entry_date=start_date,
            summary=BALANCE_FORWARD_SUMMARY,
            counterparty_account=None,
            party=None,
            debit=None,
            credit=None,
            balance=balance_forward,
            entry_id=None,
        ),
    )

    running = balance_forward
    for row in activity_rows:
        entry_id = int(row["entry_id"])
        net = Decimal(row["net_amount"])
        other_count, other_name = other_by_entry.get(entry_id, (0, None))
        party_count, party_name = party_by_entry.get(entry_id, (0, None))
        running += net

        display_rows.append(
            AccountStatementRowOut(
                row_kind="activity",
                entry_date=row["entry_date"],
                summary=row["summary"],
                counterparty_account=_counterparty_label(other_count, other_name),
                party=_party_label_from_count(party_count, party_name),
                debit=abs(net) if net > 0 else None,
                credit=abs(net) if net < 0 else None,
                balance=running,
                entry_id=entry_id,
            ),
        )

    closing_balance = running
    display_rows.append(
        AccountStatementRowOut(
            row_kind="closing_balance",
            entry_date=end_date,
            summary=CLOSING_BALANCE_SUMMARY,
            counterparty_account=None,
            party=None,
            debit=None,
            credit=None,
            balance=closing_balance,
            entry_id=None,
        ),
    )

    return AccountStatementReportOut(
        account=AccountStatementAccountEcho(
            account_id=int(account_row["id"]),
            account_name=account_row["name"],
            is_active=bool(account_row["is_active"]),
        ),
        period=AccountStatementPeriodEcho(start_date=start_date, end_date=end_date),
        currency_label=ACCOUNT_STATEMENT_CURRENCY_LABEL,
        balance_forward=balance_forward,
        closing_balance=closing_balance,
        rows=display_rows,
    )
