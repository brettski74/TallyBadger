from collections.abc import Callable
from contextlib import AbstractContextManager
from decimal import Decimal

from psycopg import errors
from psycopg.rows import dict_row

from tallybadger.db import get_connection
from tallybadger.ledger.models import (
    AccountCreate,
    AccountOut,
    JournalEntryOut,
    JournalEntryWrite,
    JournalLineOut,
)


class LedgerError(Exception):
    """Base ledger service error."""


class LedgerValidationError(LedgerError):
    """Raised when business invariants are violated."""


class LedgerConflictError(LedgerError):
    """Raised on uniqueness conflicts."""


class LedgerNotFoundError(LedgerError):
    """Raised when a ledger record does not exist."""


class LedgerService:
    def __init__(
        self,
        connection_factory: Callable[[], AbstractContextManager] = get_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def list_accounts(self) -> list[AccountOut]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, type, is_active, created_at, updated_at
                    FROM accounts
                    ORDER BY name ASC
                    """
                )
                rows = cur.fetchall()
        return [AccountOut.model_validate(row) for row in rows]

    def create_account(self, account: AccountCreate) -> AccountOut:
        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            INSERT INTO accounts (name, type, is_active)
                            VALUES (%s, %s, %s)
                            RETURNING id, name, type, is_active, created_at, updated_at
                            """,
                            (account.name.strip(), account.type, account.is_active),
                        )
                        row = cur.fetchone()
            except errors.UniqueViolation as exc:
                raise LedgerConflictError("account name already exists") from exc
        return AccountOut.model_validate(row)

    def create_entry(self, payload: JournalEntryWrite) -> JournalEntryOut:
        self._validate_lines(payload.lines)
        try:
            with self._connection_factory() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            INSERT INTO journal_entries (entry_date, description)
                            VALUES (%s, %s)
                            RETURNING id
                            """,
                            (payload.entry_date, payload.description),
                        )
                        entry_id = cur.fetchone()["id"]
                        for line in payload.lines:
                            cur.execute(
                                """
                                INSERT INTO journal_lines (entry_id, account_id, amount)
                                VALUES (%s, %s, %s)
                                """,
                                (entry_id, line.account_id, line.amount),
                            )
                        self._assert_entry_balanced(cur, entry_id)
                    return self.get_entry(entry_id, conn=conn)
        except errors.ForeignKeyViolation as exc:
            raise LedgerValidationError("journal line references unknown account") from exc

    def update_entry(self, entry_id: int, payload: JournalEntryWrite) -> JournalEntryOut:
        self._validate_lines(payload.lines)
        try:
            with self._connection_factory() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            UPDATE journal_entries
                            SET entry_date = %s, description = %s, updated_at = NOW()
                            WHERE id = %s
                            """,
                            (payload.entry_date, payload.description, entry_id),
                        )
                        if cur.rowcount == 0:
                            raise LedgerNotFoundError(f"journal entry {entry_id} not found")

                        cur.execute(
                            "DELETE FROM journal_lines WHERE entry_id = %s",
                            (entry_id,),
                        )
                        for line in payload.lines:
                            cur.execute(
                                """
                                INSERT INTO journal_lines (entry_id, account_id, amount)
                                VALUES (%s, %s, %s)
                                """,
                                (entry_id, line.account_id, line.amount),
                            )
                        self._assert_entry_balanced(cur, entry_id)
                    return self.get_entry(entry_id, conn=conn)
        except errors.ForeignKeyViolation as exc:
            raise LedgerValidationError("journal line references unknown account") from exc

    def delete_entry(self, entry_id: int) -> None:
        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM journal_entries WHERE id = %s", (entry_id,))
                    if cur.rowcount == 0:
                        raise LedgerNotFoundError(f"journal entry {entry_id} not found")

    def get_entry(self, entry_id: int, conn=None) -> JournalEntryOut:
        owns_connection = conn is None
        if owns_connection:
            connection_cm = self._connection_factory()
            conn = connection_cm.__enter__()

        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, entry_date, description, created_at, updated_at
                    FROM journal_entries
                    WHERE id = %s
                    """,
                    (entry_id,),
                )
                header = cur.fetchone()
                if not header:
                    raise LedgerNotFoundError(f"journal entry {entry_id} not found")

                cur.execute(
                    """
                    SELECT id, account_id, amount
                    FROM journal_lines
                    WHERE entry_id = %s
                    ORDER BY id ASC
                    """,
                    (entry_id,),
                )
                lines = [JournalLineOut.model_validate(row) for row in cur.fetchall()]
            return JournalEntryOut.model_validate({**header, "lines": lines})
        finally:
            if owns_connection:
                connection_cm.__exit__(None, None, None)

    @staticmethod
    def _validate_lines(lines) -> None:
        if len(lines) < 2:
            raise LedgerValidationError("journal entry requires at least two lines")
        if any(line.amount == Decimal("0") for line in lines):
            raise LedgerValidationError("journal line amounts must be non-zero")
        if sum(line.amount for line in lines) != Decimal("0"):
            raise LedgerValidationError("journal entry is not balanced")

    @staticmethod
    def _assert_entry_balanced(cur, entry_id: int) -> None:
        cur.execute(
            """
            SELECT COUNT(*) AS line_count, COALESCE(SUM(amount), 0) AS total
            FROM journal_lines
            WHERE entry_id = %s
            """,
            (entry_id,),
        )
        row = cur.fetchone()
        if row["line_count"] < 2:
            raise LedgerValidationError("journal entry requires at least two lines")
        if Decimal(row["total"]) != Decimal("0"):
            raise LedgerValidationError("journal entry is not balanced")
