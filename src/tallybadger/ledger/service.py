from collections.abc import Callable
from contextlib import AbstractContextManager
from decimal import Decimal

from psycopg import errors
from psycopg.rows import dict_row

from tallybadger.db import get_connection
from tallybadger.ledger.models import (
    AccountCreate,
    AccountOut,
    AccountLedgerLineOut,
    AccountUpdate,
    JournalEntryOut,
    JournalEntryListItem,
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

    def update_account(self, account_id: int, payload: AccountUpdate) -> AccountOut:
        if payload.name is None and payload.is_active is None:
            raise LedgerValidationError("at least one account field must be updated")

        updates: list[str] = []
        params: list[object] = []
        if payload.name is not None:
            updates.append("name = %s")
            params.append(payload.name.strip())
        if payload.is_active is not None:
            updates.append("is_active = %s")
            params.append(payload.is_active)
        params.append(account_id)

        query = f"""
            UPDATE accounts
            SET {", ".join(updates)}, updated_at = NOW()
            WHERE id = %s
            RETURNING id, name, type, is_active, created_at, updated_at
        """
        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(query, params)
                        row = cur.fetchone()
                        if not row:
                            raise LedgerNotFoundError(f"account {account_id} not found")
            except errors.UniqueViolation as exc:
                raise LedgerConflictError("account name already exists") from exc
        return AccountOut.model_validate(row)

    def list_entries(
        self,
        *,
        from_date=None,
        to_date=None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JournalEntryListItem]:
        conditions: list[str] = []
        params: list[object] = []
        if from_date is not None:
            conditions.append("je.entry_date >= %s")
            params.append(from_date)
        if to_date is not None:
            conditions.append("je.entry_date <= %s")
            params.append(to_date)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT
                        je.id,
                        je.entry_date,
                        je.description,
                        je.created_at,
                        je.updated_at,
                        COUNT(jl.id) AS line_count,
                        COALESCE(SUM(jl.amount), 0) AS total_amount
                    FROM journal_entries je
                    JOIN journal_lines jl ON jl.entry_id = je.id
                    {where_clause}
                    GROUP BY je.id
                    ORDER BY je.entry_date DESC, je.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [JournalEntryListItem.model_validate(row) for row in rows]

    def list_account_lines(
        self,
        account_id: int,
        *,
        from_date=None,
        to_date=None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AccountLedgerLineOut]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT 1 FROM accounts WHERE id = %s",
                    (account_id,),
                )
                if not cur.fetchone():
                    raise LedgerNotFoundError(f"account {account_id} not found")

                conditions = ["jl.account_id = %s"]
                params: list[object] = [account_id]
                if from_date is not None:
                    conditions.append("je.entry_date >= %s")
                    params.append(from_date)
                if to_date is not None:
                    conditions.append("je.entry_date <= %s")
                    params.append(to_date)
                params.extend([limit, offset])
                cur.execute(
                    f"""
                    SELECT
                        jl.id AS line_id,
                        je.id AS entry_id,
                        je.entry_date,
                        je.description,
                        jl.amount
                    FROM journal_lines jl
                    JOIN journal_entries je ON je.id = jl.entry_id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY je.entry_date DESC, jl.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [AccountLedgerLineOut.model_validate(row) for row in rows]

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
                            self._assert_account_active(cur, line.account_id)
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
                            self._assert_account_active(cur, line.account_id)
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

    @staticmethod
    def _assert_account_active(cur, account_id: int) -> None:
        cur.execute(
            "SELECT is_active FROM accounts WHERE id = %s",
            (account_id,),
        )
        row = cur.fetchone()
        if not row:
            raise LedgerValidationError("journal line references unknown account")
        if not row["is_active"]:
            raise LedgerValidationError(
                f"account {account_id} is deactivated; reactivate before posting"
            )
