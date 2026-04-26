from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
import calendar
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
    AccrualPlanCreate,
    AccrualPlanOut,
    AccrualPlanUpdate,
    AccrualPreviewItem,
    PartyCreate,
    PartyOut,
    PartyUpdate,
    JournalEntryOut,
    JournalEntryListItem,
    JournalEntryWrite,
    JournalLineOut,
)

class LedgerError(Exception):
    """Base ledger service error."""


class LedgerValidationError(LedgerError):
    """Raised when business invariants are violated."""


JOURNAL_LIST_SPLIT_LABEL = "-- Split --"


def labels_and_amount_for_journal_list_lines(
    lines: list[tuple[Decimal, str]],
) -> tuple[str, str, Decimal]:
    """Build debit column, credit column, and display amount from signed lines (+ debit, − credit)."""
    for _amt, name in lines:
        stripped = (name or "").strip()
        if not stripped:
            raise LedgerValidationError("journal line is missing account name for list display")

    debits = [(amt, name.strip()) for amt, name in lines if amt > 0]
    credits = [(amt, name.strip()) for amt, name in lines if amt < 0]
    if len(debits) == 1:
        debit_label = debits[0][1]
    elif len(debits) > 1:
        debit_label = JOURNAL_LIST_SPLIT_LABEL
    else:
        debit_label = "—"

    if len(credits) == 1:
        credit_label = credits[0][1]
    elif len(credits) > 1:
        credit_label = JOURNAL_LIST_SPLIT_LABEL
    else:
        credit_label = "—"

    debit_total = sum((amt for amt, _ in debits), Decimal("0"))
    if debit_total == 0 and credits:
        debit_total = sum((-amt for amt, _ in credits), Decimal("0"))
    return debit_label, credit_label, debit_total


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

    def list_parties(self) -> list[PartyOut]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, role, is_active, created_at, updated_at
                    FROM parties
                    ORDER BY name ASC
                    """
                )
                rows = cur.fetchall()
        return [PartyOut.model_validate(row) for row in rows]

    def create_party(self, party: PartyCreate) -> PartyOut:
        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            INSERT INTO parties (name, role, is_active)
                            VALUES (%s, %s, %s)
                            RETURNING id, name, role, is_active, created_at, updated_at
                            """,
                            (party.name.strip(), party.role, party.is_active),
                        )
                        row = cur.fetchone()
            except errors.UniqueViolation as exc:
                raise LedgerConflictError("party name already exists") from exc
        return PartyOut.model_validate(row)

    def update_party(self, party_id: int, payload: PartyUpdate) -> PartyOut:
        if payload.name is None and payload.role is None and payload.is_active is None:
            raise LedgerValidationError("at least one party field must be updated")

        updates: list[str] = []
        params: list[object] = []
        if payload.name is not None:
            updates.append("name = %s")
            params.append(payload.name.strip())
        if payload.role is not None:
            updates.append("role = %s")
            params.append(payload.role)
        if payload.is_active is not None:
            updates.append("is_active = %s")
            params.append(payload.is_active)
        params.append(party_id)

        query = f"""
            UPDATE parties
            SET {", ".join(updates)}, updated_at = NOW()
            WHERE id = %s
            RETURNING id, name, role, is_active, created_at, updated_at
        """
        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(query, params)
                        row = cur.fetchone()
                        if not row:
                            raise LedgerNotFoundError(f"party {party_id} not found")
            except errors.UniqueViolation as exc:
                raise LedgerConflictError("party name already exists") from exc
        return PartyOut.model_validate(row)

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

    def list_accrual_plans(self) -> list[AccrualPlanOut]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, direction, party_id, target_account_id, bridge_account_id,
                           frequency, start_date, end_date, amount, summary_template, description_template,
                           day_of_week, day_of_month, month_of_year, business_day_adjust,
                           created_at, updated_at
                    FROM accrual_plans
                    ORDER BY created_at DESC, id DESC
                    """
                )
                rows = cur.fetchall()
        return [AccrualPlanOut.model_validate(row) for row in rows]

    def preview_accrual_plan(
        self, payload: AccrualPlanCreate
    ) -> list[AccrualPreviewItem]:
        dates = self._build_frequency_dates(payload)
        return [self._preview_item_from_payload(payload, dt) for dt in dates]

    def create_accrual_plan(self, payload: AccrualPlanCreate) -> AccrualPlanOut:
        preview = self.preview_accrual_plan(payload)
        if not preview:
            raise LedgerValidationError("plan frequency produced no entries in the date range")

        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    self._assert_all_plan_references_exist(cur, payload)
                    self._assert_plan_account_direction_rules(cur, payload)
                    cur.execute(
                        """
                        INSERT INTO accrual_plans (
                            name, direction, party_id, target_account_id, bridge_account_id,
                            frequency, start_date, end_date, amount, summary_template, description_template,
                            day_of_week, day_of_month, month_of_year, business_day_adjust
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, name, direction, party_id, target_account_id, bridge_account_id,
                                  frequency, start_date, end_date, amount, summary_template, description_template,
                                  day_of_week, day_of_month, month_of_year, business_day_adjust,
                                  created_at, updated_at
                        """,
                        (
                            payload.name.strip(),
                            payload.direction,
                            payload.party_id,
                            payload.target_account_id,
                            payload.bridge_account_id,
                            payload.frequency,
                            payload.start_date,
                            payload.end_date,
                            payload.amount,
                            payload.summary_template.strip(),
                            payload.description_template,
                            payload.day_of_week,
                            payload.day_of_month,
                            payload.month_of_year,
                            payload.business_day_adjust,
                        ),
                    )
                    plan_row = cur.fetchone()
                    plan_id = plan_row["id"]
                    for item in preview:
                        cur.execute(
                            """
                            INSERT INTO journal_entries (entry_date, summary, description, accrual_plan_id)
                            VALUES (%s, %s, %s, %s)
                            RETURNING id
                            """,
                            (item.entry_date, item.summary, item.description, plan_id),
                        )
                        entry_id = cur.fetchone()["id"]
                        for line in item.lines:
                            cur.execute(
                                """
                                INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (entry_id, line.account_id, line.party_id, line.amount),
                            )
        return AccrualPlanOut.model_validate(plan_row)

    def update_accrual_plan(self, plan_id: int, payload: AccrualPlanUpdate) -> AccrualPlanOut:
        if (
            payload.name is None
            and payload.end_date is None
            and payload.amount is None
            and payload.summary_template is None
            and payload.description_template is None
        ):
            raise LedgerValidationError("at least one plan field must be updated")

        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    if not payload.force_override:
                        cur.execute(
                            """
                            SELECT 1
                            FROM journal_entries
                            WHERE accrual_plan_id = %s
                              AND entry_date <= CURRENT_DATE
                            LIMIT 1
                            """,
                            (plan_id,),
                        )
                        if cur.fetchone():
                            raise LedgerValidationError(
                                "plan has already posted entries; pass force_override=true to update"
                            )

                    updates: list[str] = []
                    params: list[object] = []
                    if payload.name is not None:
                        updates.append("name = %s")
                        params.append(payload.name.strip())
                    if payload.end_date is not None:
                        updates.append("end_date = %s")
                        params.append(payload.end_date)
                    if payload.amount is not None:
                        if payload.amount <= Decimal("0"):
                            raise LedgerValidationError("amount must be positive")
                        updates.append("amount = %s")
                        params.append(payload.amount)
                    if payload.summary_template is not None:
                        updates.append("summary_template = %s")
                        params.append(payload.summary_template.strip())
                    if payload.description_template is not None:
                        updates.append("description_template = %s")
                        params.append(payload.description_template)
                    params.append(plan_id)

                    cur.execute(
                        f"""
                        UPDATE accrual_plans
                        SET {", ".join(updates)}, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, name, direction, party_id, target_account_id, bridge_account_id,
                                  frequency, start_date, end_date, amount, summary_template, description_template,
                                  day_of_week, day_of_month, month_of_year, business_day_adjust,
                                  created_at, updated_at
                        """,
                        params,
                    )
                    row = cur.fetchone()
                    if not row:
                        raise LedgerNotFoundError(f"accrual plan {plan_id} not found")
        return AccrualPlanOut.model_validate(row)

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
        list_params = [*params, limit, offset]
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT je.id, je.entry_date, je.summary, je.description, je.created_at, je.updated_at
                    FROM journal_entries je
                    WHERE EXISTS (SELECT 1 FROM journal_lines jl WHERE jl.entry_id = je.id)
                    {where_clause.replace("WHERE", "AND") if where_clause else ""}
                    ORDER BY je.entry_date DESC, je.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    list_params,
                )
                headers = cur.fetchall()

                if not headers:
                    return []

                entry_ids = [row["id"] for row in headers]
                cur.execute(
                    """
                    SELECT jl.entry_id, jl.amount, a.name AS account_name, p.name AS party_name
                    FROM journal_lines jl
                    JOIN accounts a ON a.id = jl.account_id
                    LEFT JOIN parties p ON p.id = jl.party_id
                    WHERE jl.entry_id = ANY(%s)
                    ORDER BY jl.entry_id ASC, jl.id ASC
                    """,
                    (entry_ids,),
                )
                line_rows = cur.fetchall()

        lines_by_entry: dict[int, list[tuple[Decimal, str]]] = defaultdict(list)
        parties_by_entry: dict[int, list[str]] = defaultdict(list)
        for row in line_rows:
            lines_by_entry[row["entry_id"]].append(
                (Decimal(row["amount"]), row["account_name"]),
            )
            party_name = row["party_name"]
            if party_name and party_name not in parties_by_entry[row["entry_id"]]:
                parties_by_entry[row["entry_id"]].append(party_name)

        out: list[JournalEntryListItem] = []
        for header in headers:
            entry_id = header["id"]
            lines = lines_by_entry.get(entry_id, [])
            debit_label, credit_label, amount = labels_and_amount_for_journal_list_lines(lines)
            party_labels = ", ".join(parties_by_entry.get(entry_id, [])) or "—"
            out.append(
                JournalEntryListItem(
                    id=entry_id,
                    entry_date=header["entry_date"],
                    summary=header["summary"],
                    description=header["description"],
                    created_at=header["created_at"],
                    updated_at=header["updated_at"],
                    debit_side_label=debit_label,
                    credit_side_label=credit_label,
                    party_labels=party_labels,
                    amount=amount,
                )
            )
        return out

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
        self._validate_summary(payload.summary)
        self._validate_lines(payload.lines)
        try:
            with self._connection_factory() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        self._assert_all_line_accounts_exist(cur, payload.lines)
                        self._assert_all_line_parties_exist(cur, payload.lines)
                        cur.execute(
                            """
                            INSERT INTO journal_entries (entry_date, summary, description)
                            VALUES (%s, %s, %s)
                            RETURNING id
                            """,
                            (payload.entry_date, payload.summary.strip(), payload.description),
                        )
                        entry_id = cur.fetchone()["id"]
                        for line in payload.lines:
                            self._assert_account_active(cur, line.account_id)
                            self._assert_party_active(cur, line.party_id)
                            cur.execute(
                                """
                                INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (entry_id, line.account_id, line.party_id, line.amount),
                            )
                        self._assert_entry_balanced(cur, entry_id)
                    return self.get_entry(entry_id, conn=conn)
        except errors.ForeignKeyViolation as exc:
            raise LedgerValidationError("journal line references unknown account") from exc

    def update_entry(self, entry_id: int, payload: JournalEntryWrite) -> JournalEntryOut:
        self._validate_summary(payload.summary)
        self._validate_lines(payload.lines)
        try:
            with self._connection_factory() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        self._assert_all_line_accounts_exist(cur, payload.lines)
                        self._assert_all_line_parties_exist(cur, payload.lines)
                        cur.execute(
                            """
                            UPDATE journal_entries
                            SET entry_date = %s, summary = %s, description = %s, updated_at = NOW()
                            WHERE id = %s
                            """,
                            (payload.entry_date, payload.summary.strip(), payload.description, entry_id),
                        )
                        if cur.rowcount == 0:
                            raise LedgerNotFoundError(f"journal entry {entry_id} not found")

                        cur.execute(
                            "DELETE FROM journal_lines WHERE entry_id = %s",
                            (entry_id,),
                        )
                        for line in payload.lines:
                            self._assert_account_active(cur, line.account_id)
                            self._assert_party_active(cur, line.party_id)
                            cur.execute(
                                """
                                INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (entry_id, line.account_id, line.party_id, line.amount),
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
                    SELECT id, entry_date, summary, description, created_at, updated_at
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
                    SELECT
                        jl.id,
                        jl.account_id,
                        jl.party_id,
                        jl.amount,
                        a.name AS account_name,
                        p.name AS party_name
                    FROM journal_lines jl
                    INNER JOIN accounts a ON a.id = jl.account_id
                    LEFT JOIN parties p ON p.id = jl.party_id
                    WHERE jl.entry_id = %s
                    ORDER BY jl.id ASC
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
        for line in lines:
            if line.account_id < 1:
                raise LedgerValidationError("every journal line must reference a valid account")
        if any(line.amount == Decimal("0") for line in lines):
            raise LedgerValidationError("journal line amounts must be non-zero")
        if sum(line.amount for line in lines) != Decimal("0"):
            raise LedgerValidationError("journal entry is not balanced")

    @staticmethod
    def _validate_summary(summary: str) -> None:
        if not summary.strip():
            raise LedgerValidationError("journal entry summary is required")

    @staticmethod
    def _assert_all_line_accounts_exist(cur, lines) -> None:
        account_ids = sorted({line.account_id for line in lines})
        cur.execute(
            "SELECT id FROM accounts WHERE id = ANY(%s)",
            (account_ids,),
        )
        found = {row["id"] for row in cur.fetchall()}
        missing = set(account_ids) - found
        if missing:
            raise LedgerValidationError("journal line references unknown account")

    @staticmethod
    def _assert_all_line_parties_exist(cur, lines) -> None:
        party_ids = sorted({line.party_id for line in lines if line.party_id is not None})
        if not party_ids:
            return
        cur.execute(
            "SELECT id FROM parties WHERE id = ANY(%s)",
            (party_ids,),
        )
        found = {row["id"] for row in cur.fetchall()}
        missing = set(party_ids) - found
        if missing:
            raise LedgerValidationError("journal line references unknown party")

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

    @staticmethod
    def _assert_party_active(cur, party_id: int | None) -> None:
        if party_id is None:
            return
        cur.execute(
            "SELECT is_active FROM parties WHERE id = %s",
            (party_id,),
        )
        row = cur.fetchone()
        if not row:
            raise LedgerValidationError("journal line references unknown party")
        if not row["is_active"]:
            raise LedgerValidationError(
                f"party {party_id} is inactive; reactivate before posting"
            )

    @staticmethod
    def _safe_day(year: int, month: int, day_of_month: int) -> date:
        last = calendar.monthrange(year, month)[1]
        return date(year, month, min(day_of_month, last))

    def _build_frequency_dates(self, payload: AccrualPlanCreate) -> list[date]:
        out: list[date] = []
        current = payload.start_date
        while current <= payload.end_date:
            candidate: date | None = None
            if payload.frequency == "weekly":
                delta = (payload.day_of_week - current.weekday()) % 7  # type: ignore[operator]
                candidate = current + timedelta(days=delta)
            elif payload.frequency == "monthly_day":
                candidate = self._safe_day(current.year, current.month, payload.day_of_month)  # type: ignore[arg-type]
            elif payload.frequency == "yearly":
                candidate = self._safe_day(
                    current.year,
                    payload.month_of_year,  # type: ignore[arg-type]
                    payload.day_of_month,  # type: ignore[arg-type]
                )

            if candidate and payload.business_day_adjust and payload.frequency in {
                "monthly_day",
                "yearly",
            }:
                candidate = self._roll_forward_weekend(candidate)

            if candidate and payload.start_date <= candidate <= payload.end_date and candidate not in out:
                out.append(candidate)

            if payload.frequency == "weekly":
                current += timedelta(days=7)
            elif current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        out.sort()
        return out

    @staticmethod
    def _roll_forward_weekend(value: date) -> date:
        if value.weekday() == 5:
            return value + timedelta(days=2)
        if value.weekday() == 6:
            return value + timedelta(days=1)
        return value

    @staticmethod
    def _render_template(template: str, entry_date: date, plan_name: str) -> str:
        return (
            template.replace("{date}", entry_date.isoformat())
            .replace("{month}", entry_date.strftime("%Y-%m"))
            .replace("{plan}", plan_name.strip())
            .strip()
        )

    def _preview_item_from_payload(
        self, payload: AccrualPlanCreate, entry_date: date
    ) -> AccrualPreviewItem:
        amount = payload.amount
        if payload.direction == "revenue":
            lines = [
                {"account_id": payload.bridge_account_id, "party_id": payload.party_id, "amount": amount},
                {"account_id": payload.target_account_id, "party_id": payload.party_id, "amount": -amount},
            ]
        else:
            lines = [
                {"account_id": payload.target_account_id, "party_id": payload.party_id, "amount": amount},
                {"account_id": payload.bridge_account_id, "party_id": payload.party_id, "amount": -amount},
            ]

        description = None
        if payload.description_template is not None:
            description = self._render_template(payload.description_template, entry_date, payload.name)

        return AccrualPreviewItem(
            entry_date=entry_date,
            summary=self._render_template(payload.summary_template, entry_date, payload.name),
            description=description,
            lines=lines,
        )

    @staticmethod
    def _assert_all_plan_references_exist(cur, payload: AccrualPlanCreate) -> None:
        cur.execute("SELECT id FROM parties WHERE id = %s", (payload.party_id,))
        if not cur.fetchone():
            raise LedgerValidationError("plan references unknown party")
        cur.execute(
            "SELECT id FROM accounts WHERE id = ANY(%s)",
            ([payload.target_account_id, payload.bridge_account_id],),
        )
        found = {row["id"] for row in cur.fetchall()}
        if payload.target_account_id not in found or payload.bridge_account_id not in found:
            raise LedgerValidationError("plan references unknown account")

    @staticmethod
    def _assert_plan_account_direction_rules(cur, payload: AccrualPlanCreate) -> None:
        cur.execute(
            "SELECT id, type FROM accounts WHERE id = ANY(%s)",
            ([payload.target_account_id, payload.bridge_account_id],),
        )
        by_id = {row["id"]: row["type"] for row in cur.fetchall()}
        bridge_type = by_id.get(payload.bridge_account_id)
        target_type = by_id.get(payload.target_account_id)
        if bridge_type is None or target_type is None:
            raise LedgerValidationError("plan references unknown account")
        if payload.direction == "revenue":
            if target_type != "revenue":
                raise LedgerValidationError("revenue plan target account must be type revenue")
            if bridge_type != "asset":
                raise LedgerValidationError("revenue plan bridge account must be type asset (A/R)")
        else:
            if target_type != "expense":
                raise LedgerValidationError("expense plan target account must be type expense")
            if bridge_type != "liability":
                raise LedgerValidationError("expense plan bridge account must be type liability (A/P)")
