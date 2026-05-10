from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
import calendar
import os
import re
from contextlib import AbstractContextManager
from decimal import Decimal

from psycopg import errors
from psycopg.rows import dict_row

from tallybadger.attachments.mime_detect import detect_attachment_mime
from tallybadger.db import get_connection
from tallybadger.ledger.income_expense_report import (
    INCOME_EXPENSE_CURRENCY_LABEL,
    natural_pl_total_for_account_type,
)
from tallybadger.ledger.balance_sheet_report import (
    BALANCE_SHEET_CURRENCY_LABEL,
    natural_balance_sheet_total_for_account_type,
)
from tallybadger.ledger.models import (
    AccountCreate,
    AccountOut,
    AccountLedgerLineOut,
    AccountUpdate,
    AccrualObligationOut,
    AccrualPlanCreate,
    AccrualPlanOut,
    AccrualPlanUpdate,
    AccrualPreviewItem,
    IncomeExpenseAccountRowOut,
    IncomeExpensePeriodEcho,
    IncomeExpenseReportOut,
    BalanceSheetAccountRowOut,
    BalanceSheetBalanceCheckOut,
    BalanceSheetPeriodEcho,
    BalanceSheetReportOut,
    BalanceSheetSectionOut,
    LedgerSettingsOut,
    LedgerSettingsUpdate,
    ObligationStatusUpdate,
    PartyCreate,
    PartyOut,
    PartyUpdate,
    SettlementOut,
    SettlementWrite,
    JournalEntryAttachmentOut,
    JournalEntryOut,
    JournalEntryListItem,
    JournalEntryReviewMessageOut,
    JournalEntryWrite,
    JournalLineOut,
)

class LedgerError(Exception):
    """Base ledger service error."""


class LedgerValidationError(LedgerError):
    """Raised when business invariants are violated."""


def _coerce_new_review_messages(payload: JournalEntryWrite) -> list[str]:
    out: list[str] = []
    for item in payload.review_messages:
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _validate_review_request(payload: JournalEntryWrite, existing_message_count: int) -> None:
    new_msgs = _coerce_new_review_messages(payload)
    if payload.requires_review and not new_msgs and existing_message_count == 0:
        raise LedgerValidationError(
            "Flagging an entry for review requires at least one review message.",
        )


def read_upload_file_limited(file_obj: object, max_bytes: int) -> bytes:
    """Read until EOF, raising ``LedgerValidationError`` if more than ``max_bytes`` are read."""
    chunks: list[bytes] = []
    total = 0
    read = getattr(file_obj, "read")
    while True:
        chunk = read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise LedgerValidationError(
                f"attachment exceeds maximum size of {max_bytes} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


JOURNAL_LIST_SPLIT_LABEL = "-- Split --"


def _normalize_party_match_patterns(patterns: list[str]) -> list[str]:
    out: list[str] = []
    for raw in patterns:
        pat = raw.strip()
        if not pat:
            continue
        try:
            re.compile(pat)
        except re.error as exc:
            raise LedgerValidationError(f"invalid regex pattern: {exc}") from exc
        out.append(pat)
    return out


def _validate_party_default_accounts(
    cur,
    *,
    role: str,
    revenue_id: int | None,
    expense_id: int | None,
) -> None:
    if revenue_id is not None and role not in ("customer", "both"):
        raise LedgerValidationError(
            "default revenue account is only allowed when party role is customer or both",
        )
    if expense_id is not None and role not in ("vendor", "both"):
        raise LedgerValidationError(
            "default expense account is only allowed when party role is vendor or both",
        )
    if revenue_id is not None:
        cur.execute(
            "SELECT name, type, is_active FROM accounts WHERE id = %s",
            (revenue_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise LedgerValidationError("default revenue/equity account not found")
        if not row["is_active"]:
            raise LedgerValidationError("default revenue/equity account must be active")
        if row["type"] not in ("revenue", "equity"):
            raise LedgerValidationError(
                "default revenue/equity account must have account type revenue or equity",
            )
    if expense_id is not None:
        cur.execute(
            "SELECT name, type, is_active FROM accounts WHERE id = %s",
            (expense_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise LedgerValidationError("default expense account not found")
        if not row["is_active"]:
            raise LedgerValidationError("default expense account must be active")
        if row["type"] != "expense":
            raise LedgerValidationError("default expense account must have account type expense")


def _row_to_party_out(row: dict[str, object]) -> PartyOut:
    mp = row.get("match_patterns")
    if mp is None:
        patterns: list[str] = []
    elif isinstance(mp, list):
        patterns = [str(x) for x in mp]
    else:
        patterns = [str(x) for x in list(mp)]  # type: ignore[arg-type]
    payload = {
        **{k: v for k, v in row.items() if k != "match_patterns"},
        "match_patterns": patterns,
    }
    return PartyOut.model_validate(payload)


def _party_out_by_id(cur, party_id: int) -> PartyOut | None:
    cur.execute(
        """
        SELECT p.id, p.name, p.role, p.is_active, p.subtype,
               p.default_revenue_account_id, p.default_expense_account_id,
               ra.name AS default_revenue_account_name,
               ea.name AS default_expense_account_name,
               p.created_at, p.updated_at,
               COALESCE(
                 (SELECT json_agg(pm.pattern ORDER BY pm.sort_order, pm.id)
                  FROM party_match_patterns pm WHERE pm.party_id = p.id),
                 '[]'::json
               ) AS match_patterns
        FROM parties p
        LEFT JOIN accounts ra ON ra.id = p.default_revenue_account_id
        LEFT JOIN accounts ea ON ea.id = p.default_expense_account_id
        WHERE p.id = %s
        """,
        (party_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _row_to_party_out(row)


def _replace_party_patterns(cur, party_id: int, patterns: list[str]) -> None:
    cur.execute("DELETE FROM party_match_patterns WHERE party_id = %s", (party_id,))
    for i, pat in enumerate(patterns):
        cur.execute(
            """
            INSERT INTO party_match_patterns (party_id, pattern, sort_order)
            VALUES (%s, %s, %s)
            """,
            (party_id, pat, i),
        )


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
                    SELECT p.id, p.name, p.role, p.is_active, p.subtype,
                           p.default_revenue_account_id, p.default_expense_account_id,
                           ra.name AS default_revenue_account_name,
                           ea.name AS default_expense_account_name,
                           p.created_at, p.updated_at,
                           COALESCE(
                             (SELECT json_agg(pm.pattern ORDER BY pm.sort_order, pm.id)
                              FROM party_match_patterns pm WHERE pm.party_id = p.id),
                             '[]'::json
                           ) AS match_patterns
                    FROM parties p
                    LEFT JOIN accounts ra ON ra.id = p.default_revenue_account_id
                    LEFT JOIN accounts ea ON ea.id = p.default_expense_account_id
                    ORDER BY p.name ASC
                    """
                )
                rows = cur.fetchall()
        return [_row_to_party_out(row) for row in rows]

    def list_party_subtype_suggestions(self) -> list[str]:
        with self._connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT BTRIM(subtype) AS s
                    FROM parties
                    WHERE subtype IS NOT NULL AND BTRIM(subtype) <> ''
                    ORDER BY 1 ASC
                    """
                )
                return [str(r[0]) for r in cur.fetchall()]

    def create_party(self, party: PartyCreate) -> PartyOut:
        patterns = _normalize_party_match_patterns(party.match_patterns)
        subtype = party.subtype.strip() if party.subtype and party.subtype.strip() else None
        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        _validate_party_default_accounts(
                            cur,
                            role=party.role,
                            revenue_id=party.default_revenue_account_id,
                            expense_id=party.default_expense_account_id,
                        )
                        cur.execute(
                            """
                            INSERT INTO parties (
                                name, role, is_active, subtype,
                                default_revenue_account_id, default_expense_account_id
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                party.name.strip(),
                                party.role,
                                party.is_active,
                                subtype,
                                party.default_revenue_account_id,
                                party.default_expense_account_id,
                            ),
                        )
                        row = cur.fetchone()
                        assert row is not None
                        party_id = int(row["id"])
                        _replace_party_patterns(cur, party_id, patterns)
                        out = _party_out_by_id(cur, party_id)
            except errors.CheckViolation as exc:
                raise LedgerValidationError(
                    "party role is incompatible with default account columns",
                ) from exc
            except errors.UniqueViolation as exc:
                raise LedgerConflictError("party name already exists") from exc
        assert out is not None
        return out

    def update_party(self, party_id: int, payload: PartyUpdate) -> PartyOut:
        data = payload.model_dump(exclude_unset=True)
        if not data:
            raise LedgerValidationError("at least one party field must be updated")

        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            SELECT id, name, role, is_active, subtype,
                                   default_revenue_account_id, default_expense_account_id,
                                   created_at, updated_at
                            FROM parties WHERE id = %s
                            """,
                            (party_id,),
                        )
                        current = cur.fetchone()
                        if not current:
                            raise LedgerNotFoundError(f"party {party_id} not found")

                        effective_role = data.get("role", current["role"])
                        effective_rev = current["default_revenue_account_id"]
                        if "default_revenue_account_id" in data:
                            effective_rev = data["default_revenue_account_id"]
                        effective_exp = current["default_expense_account_id"]
                        if "default_expense_account_id" in data:
                            effective_exp = data["default_expense_account_id"]

                        _validate_party_default_accounts(
                            cur,
                            role=str(effective_role),
                            revenue_id=effective_rev,
                            expense_id=effective_exp,
                        )

                        updates: list[str] = []
                        params: list[object] = []
                        if "name" in data:
                            updates.append("name = %s")
                            params.append(str(data["name"]).strip())
                        if "role" in data:
                            updates.append("role = %s")
                            params.append(data["role"])
                        if "is_active" in data:
                            updates.append("is_active = %s")
                            params.append(data["is_active"])
                        if "subtype" in data:
                            updates.append("subtype = %s")
                            st = data["subtype"]
                            if st is None:
                                params.append(None)
                            else:
                                params.append(str(st).strip() or None)
                        if "default_revenue_account_id" in data:
                            updates.append("default_revenue_account_id = %s")
                            params.append(data["default_revenue_account_id"])
                        if "default_expense_account_id" in data:
                            updates.append("default_expense_account_id = %s")
                            params.append(data["default_expense_account_id"])

                        if updates:
                            params.append(party_id)
                            cur.execute(
                                f"""
                                UPDATE parties
                                SET {", ".join(updates)}, updated_at = NOW()
                                WHERE id = %s
                                """,
                                params,
                            )

                        if "match_patterns" in data:
                            raw_patterns = data["match_patterns"]
                            if raw_patterns is None:
                                raise LedgerValidationError("match_patterns cannot be null")
                            patterns = _normalize_party_match_patterns(list(raw_patterns))
                            _replace_party_patterns(cur, party_id, patterns)

                        out = _party_out_by_id(cur, party_id)
            except errors.CheckViolation as exc:
                raise LedgerValidationError(
                    "party role is incompatible with default account columns",
                ) from exc
            except errors.UniqueViolation as exc:
                raise LedgerConflictError("party name already exists") from exc

        assert out is not None
        return out

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
                        bridge_line_id = None
                        bridge_amount = Decimal("0")
                        for line in item.lines:
                            cur.execute(
                                """
                                INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
                                VALUES (%s, %s, %s, %s)
                                RETURNING id
                                """,
                                (entry_id, line.account_id, line.party_id, line.amount),
                            )
                            line_id = cur.fetchone()["id"]
                            if line.account_id == payload.bridge_account_id:
                                bridge_line_id = line_id
                                bridge_amount = abs(Decimal(line.amount))
                        if bridge_line_id is not None:
                            obligation_type = "receivable" if payload.direction == "revenue" else "payable"
                            cur.execute(
                                """
                                INSERT INTO accrual_obligations (
                                    party_id, accrual_plan_id, source_entry_id, source_line_id,
                                    obligation_type, status, original_amount, open_amount
                                )
                                VALUES (%s, %s, %s, %s, %s, 'open', %s, %s)
                                """,
                                (
                                    payload.party_id,
                                    plan_id,
                                    entry_id,
                                    bridge_line_id,
                                    obligation_type,
                                    bridge_amount,
                                    bridge_amount,
                                ),
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

    def get_ledger_settings(self) -> LedgerSettingsOut:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT accounts_receivable_account_id, accounts_payable_account_id,
                           unearned_revenue_account_id,
                           unallocated_debits_account_id, unallocated_credits_account_id,
                           max_attachment_upload_bytes,
                           updated_at
                    FROM ledger_settings
                    WHERE id = 1
                    """
                )
                row = cur.fetchone()
                if not row:
                    raise LedgerValidationError("ledger settings row is missing")
        return LedgerSettingsOut.model_validate(row)

    def update_ledger_settings(self, payload: LedgerSettingsUpdate) -> LedgerSettingsOut:
        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    if payload.accounts_receivable_account_id is not None:
                        self._assert_account_type(cur, payload.accounts_receivable_account_id, "asset")
                    if payload.accounts_payable_account_id is not None:
                        self._assert_account_type(cur, payload.accounts_payable_account_id, "liability")
                    if payload.unearned_revenue_account_id is not None:
                        self._assert_account_type(cur, payload.unearned_revenue_account_id, "liability")
                    if payload.unallocated_debits_account_id is not None:
                        self._assert_account_type(cur, payload.unallocated_debits_account_id, "suspense")
                    if payload.unallocated_credits_account_id is not None:
                        self._assert_account_type(cur, payload.unallocated_credits_account_id, "suspense")
                    cur.execute(
                        """
                        UPDATE ledger_settings
                        SET accounts_receivable_account_id = COALESCE(%s, accounts_receivable_account_id),
                            accounts_payable_account_id = COALESCE(%s, accounts_payable_account_id),
                            unearned_revenue_account_id = COALESCE(%s, unearned_revenue_account_id),
                            unallocated_debits_account_id = COALESCE(
                                %s, unallocated_debits_account_id
                            ),
                            unallocated_credits_account_id = COALESCE(
                                %s, unallocated_credits_account_id
                            ),
                            max_attachment_upload_bytes = COALESCE(
                                %s, max_attachment_upload_bytes
                            ),
                            updated_at = NOW()
                        WHERE id = 1
                        RETURNING accounts_receivable_account_id, accounts_payable_account_id,
                                  unearned_revenue_account_id,
                                  unallocated_debits_account_id, unallocated_credits_account_id,
                                  max_attachment_upload_bytes,
                                  updated_at
                        """,
                        (
                            payload.accounts_receivable_account_id,
                            payload.accounts_payable_account_id,
                            payload.unearned_revenue_account_id,
                            payload.unallocated_debits_account_id,
                            payload.unallocated_credits_account_id,
                            payload.max_attachment_upload_bytes,
                        ),
                    )
                    row = cur.fetchone()
        return LedgerSettingsOut.model_validate(row)

    def list_open_obligations(self, party_id: int) -> list[AccrualObligationOut]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT ao.id, ao.party_id, ao.accrual_plan_id, ao.source_entry_id,
                           je.entry_date AS source_entry_date,
                           je.summary AS source_entry_summary,
                           ao.source_line_id, ao.obligation_type, ao.status,
                           ao.original_amount, ao.open_amount, ao.created_at, ao.updated_at
                    FROM accrual_obligations ao
                    LEFT JOIN journal_entries je ON je.id = ao.source_entry_id
                    WHERE ao.party_id = %s
                      AND ao.status IN ('open', 'partially_settled')
                    ORDER BY ao.created_at ASC, ao.id ASC
                    """,
                    (party_id,),
                )
                rows = cur.fetchall()
        return [AccrualObligationOut.model_validate(row) for row in rows]

    def update_obligation_status(
        self, obligation_id: int, payload: ObligationStatusUpdate
    ) -> AccrualObligationOut:
        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT status FROM accrual_obligations WHERE id = %s",
                        (obligation_id,),
                    )
                    current = cur.fetchone()
                    if not current:
                        raise LedgerNotFoundError(f"obligation {obligation_id} not found")
                    if current["status"] in {"settled", "reconciled"} and not payload.force_override:
                        raise LedgerValidationError(
                            "obligation already settled/reconciled; pass force_override=true to change status"
                        )
                    cur.execute(
                        """
                        UPDATE accrual_obligations
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, party_id, accrual_plan_id, source_entry_id, source_line_id,
                                  obligation_type, status, original_amount, open_amount, created_at, updated_at
                        """,
                        (payload.status, obligation_id),
                    )
                    row = cur.fetchone()
        return AccrualObligationOut.model_validate(row)

    def record_settlement(self, payload: SettlementWrite) -> SettlementOut:
        allocated_total = sum((item.amount for item in payload.allocations), Decimal("0"))
        if allocated_total > payload.amount:
            raise LedgerValidationError("allocated amount cannot exceed settlement amount")
        if payload.settlement_type == "payment" and allocated_total != payload.amount:
            raise LedgerValidationError("payment settlement amount must equal allocated amount")

        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    settings = self._fetch_settings_row(cur)
                    if payload.settlement_type == "receipt":
                        if settings["accounts_receivable_account_id"] is None:
                            raise LedgerValidationError("configure accounts receivable account in ledger settings first")
                    else:
                        if settings["accounts_payable_account_id"] is None:
                            raise LedgerValidationError("configure accounts payable account in ledger settings first")

                    self._assert_account_active(cur, payload.cash_account_id)
                    obligations = self._load_settlement_obligations(cur, payload.party_id, payload.allocations)
                    self._validate_obligation_types_for_settlement(payload.settlement_type, obligations)
                    self._validate_allocation_amounts(payload.allocations, obligations)
                    allocation_by_id = {item.obligation_id: item.amount for item in payload.allocations}
                    due_allocated = Decimal("0")
                    early_allocated = Decimal("0")
                    if payload.settlement_type == "receipt":
                        due_allocated, early_allocated = self._split_receipt_allocations(
                            payload.event_date,
                            obligations,
                            allocation_by_id,
                        )
                        if (early_allocated > 0 or payload.amount > allocated_total) and settings["unearned_revenue_account_id"] is None:
                            raise LedgerValidationError("configure unearned revenue account for early/over receipts")

                    collapse_same_day = (
                        payload.settlement_type == "receipt"
                        and self._receipt_allocations_all_same_accrual_day(
                            obligations, allocation_by_id, payload.event_date
                        )
                    )

                    touched_entry_ids: set[int] = set()
                    if collapse_same_day:
                        primary_entry_id: int | None = None
                        ar_id = settings["accounts_receivable_account_id"]
                        for obligation in obligations:
                            alloc_amt = allocation_by_id[obligation["id"]]
                            if alloc_amt <= Decimal("0"):
                                continue
                            accrual_eid = obligation["source_entry_id"]
                            touched_entry_ids.add(accrual_eid)
                            if primary_entry_id is None:
                                primary_entry_id = accrual_eid
                            self._same_day_settle_receivable_obligation(
                                cur,
                                obligation,
                                alloc_amt,
                                payload.cash_account_id,
                                ar_id,
                            )
                        assert primary_entry_id is not None
                        unapplied = payload.amount - allocated_total
                        if unapplied > Decimal("0"):
                            ur_id = settings["unearned_revenue_account_id"]
                            self._assert_account_active(cur, ur_id)
                            self._append_cash_and_unearned_lines(
                                cur,
                                primary_entry_id,
                                payload.party_id,
                                payload.cash_account_id,
                                ur_id,
                                unapplied,
                            )
                        for eid in touched_entry_ids:
                            cur.execute(
                                "UPDATE journal_entries SET updated_at = NOW() WHERE id = %s",
                                (eid,),
                            )
                        entry_id = primary_entry_id
                    else:
                        settlement_summary = self._settlement_journal_summary(obligations, allocation_by_id)

                        cur.execute(
                            """
                            INSERT INTO journal_entries (entry_date, summary, description)
                            VALUES (%s, %s, %s)
                            RETURNING id
                            """,
                            (
                                payload.event_date,
                                settlement_summary,
                                payload.note,
                            ),
                        )
                        entry_id = cur.fetchone()["id"]
                        self._insert_settlement_journal_lines(
                            cur,
                            payload,
                            settings,
                            entry_id,
                            allocated_total,
                            due_allocated=due_allocated,
                            early_allocated=early_allocated,
                        )
                        touched_entry_ids = {entry_id}

                    cur.execute(
                        """
                        INSERT INTO settlement_events (party_id, settlement_type, event_date, amount, cash_account_id, entry_id, note)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            payload.party_id,
                            payload.settlement_type,
                            payload.event_date,
                            payload.amount,
                            payload.cash_account_id,
                            entry_id,
                            payload.note,
                        ),
                    )
                    event_id = cur.fetchone()["id"]
                    for obligation in obligations:
                        alloc_amt = allocation_by_id[obligation["id"]]
                        cur.execute(
                            """
                            INSERT INTO settlement_allocations (settlement_event_id, obligation_id, amount)
                            VALUES (%s, %s, %s)
                            """,
                            (event_id, obligation["id"], alloc_amt),
                        )
                        open_after = Decimal(obligation["open_amount"]) - alloc_amt
                        new_status = "settled" if open_after == Decimal("0") else "partially_settled"
                        cur.execute(
                            """
                            UPDATE accrual_obligations
                            SET open_amount = %s, status = %s, updated_at = NOW()
                            WHERE id = %s
                            """,
                            (open_after, new_status, obligation["id"]),
                        )
                        if (
                            not collapse_same_day
                            and payload.settlement_type == "receipt"
                            and obligation.get("source_entry_date") is not None
                            and obligation["source_entry_date"] > payload.event_date
                            and alloc_amt > Decimal("0")
                        ):
                            if obligation.get("source_line_id") is None:
                                raise LedgerValidationError(
                                    "future receivable obligation is missing source line for unearned reclassification"
                                )
                            self._reclassify_receivable_line_to_unearned(
                                cur,
                                obligation_id=obligation["id"],
                                source_line_id=obligation["source_line_id"],
                                ar_account_id=settings["accounts_receivable_account_id"],
                                unearned_account_id=settings["unearned_revenue_account_id"],
                                allocation_amount=alloc_amt,
                            )
                    for eid in touched_entry_ids:
                        self._assert_entry_balanced(cur, eid)
        return SettlementOut(
            event_id=event_id,
            entry_id=entry_id,
            allocated_amount=allocated_total,
            unapplied_amount=payload.amount - allocated_total,
        )

    def list_entries(
        self,
        *,
        from_date=None,
        to_date=None,
        needs_review: bool | None = None,
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
        if needs_review is True:
            conditions.append("je.requires_review IS TRUE")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        list_params = [*params, limit, offset]
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT je.id, je.entry_date, je.summary, je.description, je.requires_review,
                           je.created_at, je.updated_at
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
                    requires_review=bool(header.get("requires_review")),
                    created_at=header["created_at"],
                    updated_at=header["updated_at"],
                    debit_side_label=debit_label,
                    credit_side_label=credit_label,
                    party_labels=party_labels,
                    amount=amount,
                )
            )
        return out

    def income_expense_report(
        self,
        *,
        start_date: date,
        end_date: date,
        exclude_zero_balance_accounts: bool,
        preset: str | None = None,
    ) -> IncomeExpenseReportOut:
        """Aggregate posted P&L lines for ``[start_date, end_date]`` inclusive on ``entry_date``."""
        if end_date < start_date:
            raise LedgerValidationError("end_date must be on or after start_date")

        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT a.id, a.name, a.type, a.is_active,
                           COALESCE(SUM(pl.amount), 0) AS raw_line_total
                    FROM accounts a
                    LEFT JOIN (
                        SELECT jl.account_id, jl.amount
                        FROM journal_lines jl
                        INNER JOIN journal_entries je ON je.id = jl.entry_id
                          AND je.entry_date >= %s AND je.entry_date <= %s
                    ) pl ON pl.account_id = a.id
                    WHERE a.type IN ('revenue', 'expense')
                    GROUP BY a.id, a.name, a.type, a.is_active
                    """,
                    (start_date, end_date),
                )
                raw_rows = cur.fetchall()

        rows_sorted = sorted(raw_rows, key=lambda r: str(r["name"]))

        revenue_all: list[IncomeExpenseAccountRowOut] = []
        expense_all: list[IncomeExpenseAccountRowOut] = []
        total_revenue = Decimal("0")
        total_expense = Decimal("0")

        for row in rows_sorted:
            acct_type = row["type"]
            raw_total = Decimal(row["raw_line_total"])
            natural = natural_pl_total_for_account_type(acct_type, raw_total)
            out_row = IncomeExpenseAccountRowOut(
                account_id=row["id"],
                account_name=row["name"],
                account_type=acct_type,
                is_active=bool(row["is_active"]),
                amount=natural,
            )
            if acct_type == "revenue":
                revenue_all.append(out_row)
                total_revenue += natural
            else:
                expense_all.append(out_row)
                total_expense += natural

        if exclude_zero_balance_accounts:
            revenue_accounts = [r for r in revenue_all if r.amount != Decimal("0")]
            expense_accounts = [r for r in expense_all if r.amount != Decimal("0")]
        else:
            revenue_accounts = revenue_all
            expense_accounts = expense_all

        net_income = total_revenue - total_expense
        preset_out = (
            preset
            if preset in ("current_year_to_date", "prior_full_year", "prior_year_to_date")
            else None
        )

        return IncomeExpenseReportOut(
            period=IncomeExpensePeriodEcho(start_date=start_date, end_date=end_date),
            currency_label=INCOME_EXPENSE_CURRENCY_LABEL,
            preset=preset_out,
            exclude_zero_balance_accounts=exclude_zero_balance_accounts,
            revenue_accounts=revenue_accounts,
            expense_accounts=expense_accounts,
            total_revenue=total_revenue,
            total_expense=total_expense,
            net_income=net_income,
        )

    def balance_sheet_report(
        self,
        *,
        as_of_date: date,
        exclude_requires_review: bool,
        preset: str | None = None,
    ) -> BalanceSheetReportOut:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                review_filter = ""
                params: list[object] = [as_of_date]
                if exclude_requires_review:
                    review_filter = "AND je.requires_review IS NOT TRUE"

                cur.execute(
                    f"""
                    SELECT a.id, a.name, a.type, a.is_active, COALESCE(SUM(jl.amount), 0) AS raw_line_total
                    FROM accounts a
                    LEFT JOIN (
                        SELECT jl.account_id, jl.amount
                        FROM journal_lines jl
                        INNER JOIN journal_entries je ON je.id = jl.entry_id
                          AND je.entry_date <= %s
                          {review_filter}
                    ) jl ON jl.account_id = a.id
                    WHERE a.type IN ('asset', 'liability', 'equity')
                    GROUP BY a.id, a.name, a.type, a.is_active
                    """,
                    params,
                )
                raw_bs_rows = cur.fetchall()

                cur.execute(
                    f"""
                    SELECT a.type, COALESCE(SUM(pl.amount), 0) AS raw_line_total
                    FROM accounts a
                    LEFT JOIN (
                        SELECT jl.account_id, jl.amount
                        FROM journal_lines jl
                        INNER JOIN journal_entries je ON je.id = jl.entry_id
                          AND je.entry_date <= %s
                          {review_filter}
                    ) pl ON pl.account_id = a.id
                    WHERE a.type IN ('revenue', 'expense')
                    GROUP BY a.type
                    """,
                    params,
                )
                raw_pl_rows = cur.fetchall()

        rows_sorted = sorted(raw_bs_rows, key=lambda r: str(r["name"]))
        assets_accounts: list[BalanceSheetAccountRowOut] = []
        liabilities_accounts: list[BalanceSheetAccountRowOut] = []
        equity_accounts: list[BalanceSheetAccountRowOut] = []
        assets_total = Decimal("0")
        liabilities_total = Decimal("0")
        equity_ledger_total = Decimal("0")

        for row in rows_sorted:
            acct_type = str(row["type"])
            natural = natural_balance_sheet_total_for_account_type(
                acct_type,
                Decimal(row["raw_line_total"]),
            )
            out_row = BalanceSheetAccountRowOut(
                account_id=int(row["id"]),
                account_name=str(row["name"]),
                account_type=acct_type,  # type: ignore[arg-type]
                is_active=bool(row["is_active"]),
                is_computed=False,
                amount=natural,
            )
            if acct_type == "asset":
                assets_accounts.append(out_row)
                assets_total += natural
            elif acct_type == "liability":
                liabilities_accounts.append(out_row)
                liabilities_total += natural
            else:
                equity_accounts.append(out_row)
                equity_ledger_total += natural

        pl_by_type: dict[str, Decimal] = {"revenue": Decimal("0"), "expense": Decimal("0")}
        for row in raw_pl_rows:
            acct_type = str(row["type"])
            pl_by_type[acct_type] = natural_pl_total_for_account_type(
                acct_type,
                Decimal(row["raw_line_total"]),
            )
        retained_earnings = pl_by_type["revenue"] - pl_by_type["expense"]
        equity_accounts.append(
            BalanceSheetAccountRowOut(
                account_id=None,
                account_name="Retained Earnings",
                account_type="computed_equity",
                is_active=None,
                is_computed=True,
                amount=retained_earnings,
            )
        )
        equity_total = equity_ledger_total + retained_earnings
        liabilities_plus_equity = liabilities_total + equity_total
        difference = assets_total - liabilities_plus_equity

        preset_out = preset if preset in ("today", "prior_year_end") else None
        return BalanceSheetReportOut(
            period=BalanceSheetPeriodEcho(as_of_date=as_of_date),
            currency_label=BALANCE_SHEET_CURRENCY_LABEL,
            preset=preset_out,
            exclude_requires_review=exclude_requires_review,
            assets=BalanceSheetSectionOut(
                section="assets",
                label="Assets",
                accounts=assets_accounts,
                total=assets_total,
            ),
            liabilities=BalanceSheetSectionOut(
                section="liabilities",
                label="Liabilities",
                accounts=liabilities_accounts,
                total=liabilities_total,
            ),
            equity=BalanceSheetSectionOut(
                section="equity",
                label="Equity",
                accounts=equity_accounts,
                total=equity_total,
            ),
            balance_check=BalanceSheetBalanceCheckOut(
                assets_total=assets_total,
                liabilities_total=liabilities_total,
                equity_total=equity_total,
                liabilities_plus_equity=liabilities_plus_equity,
                is_balanced=difference == Decimal("0"),
                difference=difference,
            ),
        )

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
        _validate_review_request(payload, 0)
        new_review = _coerce_new_review_messages(payload)
        try:
            with self._connection_factory() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        self._assert_all_line_accounts_exist(cur, payload.lines)
                        self._assert_all_line_parties_exist(cur, payload.lines)
                        cur.execute(
                            """
                            INSERT INTO journal_entries (entry_date, summary, description, requires_review)
                            VALUES (%s, %s, %s, FALSE)
                            RETURNING id
                            """,
                            (
                                payload.entry_date,
                                payload.summary.strip(),
                                payload.description,
                            ),
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
                        self._insert_review_messages(cur, entry_id, new_review)
                    return self.get_entry(entry_id, conn=conn)
        except errors.ForeignKeyViolation as exc:
            raise LedgerValidationError("journal line references unknown account") from exc

    def create_entries_batch(self, payloads: list[JournalEntryWrite]) -> list[JournalEntryOut]:
        if not payloads:
            return []
        for payload in payloads:
            self._validate_summary(payload.summary)
            self._validate_lines(payload.lines)
            _validate_review_request(payload, 0)
        created_ids: list[int] = []
        try:
            with self._connection_factory() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        for payload in payloads:
                            self._assert_all_line_accounts_exist(cur, payload.lines)
                            self._assert_all_line_parties_exist(cur, payload.lines)
                            cur.execute(
                                """
                                INSERT INTO journal_entries (entry_date, summary, description, requires_review)
                                VALUES (%s, %s, %s, FALSE)
                                RETURNING id
                                """,
                                (
                                    payload.entry_date,
                                    payload.summary.strip(),
                                    payload.description,
                                ),
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
                            self._insert_review_messages(
                                cur,
                                entry_id,
                                _coerce_new_review_messages(payload),
                            )
                            created_ids.append(entry_id)
                    return [self.get_entry(entry_id, conn=conn) for entry_id in created_ids]
        except errors.ForeignKeyViolation as exc:
            raise LedgerValidationError("journal line references unknown account") from exc

    def update_entry(self, entry_id: int, payload: JournalEntryWrite) -> JournalEntryOut:
        self._validate_summary(payload.summary)
        self._validate_lines(payload.lines)
        new_review = _coerce_new_review_messages(payload)
        try:
            with self._connection_factory() as conn:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            SELECT COUNT(*)::int AS c
                            FROM journal_entry_review_messages
                            WHERE journal_entry_id = %s
                            """,
                            (entry_id,),
                        )
                        existing_review_ct = int(cur.fetchone()["c"])
                        _validate_review_request(payload, existing_review_ct)

                        self._assert_all_line_accounts_exist(cur, payload.lines)
                        self._assert_all_line_parties_exist(cur, payload.lines)
                        cur.execute(
                            """
                            UPDATE journal_entries
                            SET entry_date = %s, summary = %s, description = %s, updated_at = NOW()
                            WHERE id = %s
                            """,
                            (
                                payload.entry_date,
                                payload.summary.strip(),
                                payload.description,
                                entry_id,
                            ),
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
                        self._insert_review_messages(cur, entry_id, new_review)
                    return self.get_entry(entry_id, conn=conn)
        except errors.ForeignKeyViolation as exc:
            raise LedgerValidationError("journal line references unknown account") from exc

    def delete_journal_entry_review_message(self, entry_id: int, message_id: int) -> None:
        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM journal_entries WHERE id = %s",
                        (entry_id,),
                    )
                    if cur.fetchone() is None:
                        raise LedgerNotFoundError(f"journal entry {entry_id} not found")
                    cur.execute(
                        """
                        DELETE FROM journal_entry_review_messages
                        WHERE id = %s AND journal_entry_id = %s
                        """,
                        (message_id, entry_id),
                    )

    @staticmethod
    def _insert_review_messages(cur, entry_id: int, messages: list[str]) -> None:
        for msg in messages:
            cur.execute(
                """
                INSERT INTO journal_entry_review_messages (journal_entry_id, message)
                VALUES (%s, %s)
                """,
                (entry_id, msg),
            )

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
                    SELECT id, entry_date, summary, description, requires_review, created_at, updated_at
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

                cur.execute(
                    """
                    SELECT id, message, created_at
                    FROM journal_entry_review_messages
                    WHERE journal_entry_id = %s
                    ORDER BY id ASC
                    """,
                    (entry_id,),
                )
                review_rows = cur.fetchall()
                review_messages = [JournalEntryReviewMessageOut.model_validate(r) for r in review_rows]
            return JournalEntryOut.model_validate(
                {**header, "lines": lines, "review_messages": review_messages},
            )
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
    def _assert_account_type(cur, account_id: int, expected_type: str) -> None:
        cur.execute("SELECT type FROM accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
        if not row:
            raise LedgerValidationError(f"account {account_id} not found")
        if row["type"] != expected_type:
            raise LedgerValidationError(f"account {account_id} must be type {expected_type}")

    @staticmethod
    def _fetch_settings_row(cur):
        cur.execute(
            """
            SELECT accounts_receivable_account_id, accounts_payable_account_id, unearned_revenue_account_id
            FROM ledger_settings
            WHERE id = 1
            """
        )
        row = cur.fetchone()
        if not row:
            raise LedgerValidationError("ledger settings row is missing")
        return row

    @staticmethod
    def _load_settlement_obligations(cur, party_id: int, allocations):
        obligation_ids = [item.obligation_id for item in allocations]
        cur.execute(
            """
            SELECT id, party_id, obligation_type, status, open_amount, source_entry_id, source_line_id
            FROM accrual_obligations
            WHERE id = ANY(%s)
            FOR UPDATE
            """,
            (obligation_ids,),
        )
        rows = cur.fetchall()
        if len(rows) != len(obligation_ids):
            raise LedgerValidationError("one or more obligations do not exist")
        by_id = {row["id"]: row for row in rows}
        ordered = [by_id[oid] for oid in obligation_ids]
        for row in ordered:
            if row["party_id"] != party_id:
                raise LedgerValidationError("all obligations must belong to the selected party")
            if row["status"] in {"settled", "reconciled"}:
                raise LedgerValidationError("cannot settle obligations that are already settled/reconciled")
            if row["source_entry_id"] is None:
                row["source_entry_date"] = None
                row["source_entry_summary"] = None
                continue
            cur.execute(
                "SELECT entry_date, summary FROM journal_entries WHERE id = %s",
                (row["source_entry_id"],),
            )
            source = cur.fetchone()
            row["source_entry_date"] = source["entry_date"] if source else None
            row["source_entry_summary"] = (
                (source["summary"] or "").strip() or None if source else None
            )
        return ordered

    @staticmethod
    def _settlement_journal_summary(obligations, allocation_by_id: dict[int, Decimal]) -> str:
        """Earliest source accrual (by entry date, then id) among obligations with positive allocation."""
        candidates: list[tuple[date, int, str | None]] = []
        for row in obligations:
            if allocation_by_id[row["id"]] <= Decimal("0"):
                continue
            eid = row.get("source_entry_id")
            if eid is None:
                continue
            ed = row.get("source_entry_date")
            if ed is None:
                continue
            summ = row.get("source_entry_summary")
            candidates.append((ed, eid, (summ or "").strip() or None))
        if not candidates:
            return "Settlement"
        _ed, _eid, accrual_summary = min(candidates, key=lambda c: (c[0], c[1]))
        if not accrual_summary:
            return "Settlement"
        return f"Settlement {accrual_summary}"

    @staticmethod
    def _receipt_allocations_all_same_accrual_day(
        obligations, allocation_by_id: dict[int, Decimal], event_date: date
    ) -> bool:
        """True when every positively allocated receipt obligation is tied to an accrual dated event_date."""
        saw_allocation = False
        for row in obligations:
            if allocation_by_id[row["id"]] <= Decimal("0"):
                continue
            saw_allocation = True
            if row.get("source_entry_id") is None or row.get("source_line_id") is None:
                return False
            sd = row.get("source_entry_date")
            if sd is None or sd != event_date:
                return False
        return saw_allocation

    @staticmethod
    def _same_day_settle_receivable_obligation(
        cur,
        obligation: dict,
        allocation_amount: Decimal,
        cash_account_id: int,
        ar_account_id: int,
    ) -> None:
        """Move allocated amount from A/R to cash on the accrual entry (same calendar day as settlement)."""
        source_line_id = obligation["source_line_id"]
        cur.execute(
            """
            SELECT entry_id, party_id, account_id, amount
            FROM journal_lines
            WHERE id = %s
            FOR UPDATE
            """,
            (source_line_id,),
        )
        line = cur.fetchone()
        if not line:
            raise LedgerValidationError("obligation source line not found for same-day settlement")
        if line["account_id"] != ar_account_id:
            raise LedgerValidationError(
                "same-day receipt settlement expects the obligation bridge on accounts receivable"
            )
        current = Decimal(line["amount"])
        sign = Decimal("1") if current >= Decimal("0") else Decimal("-1")
        allocated_signed = sign * allocation_amount
        remaining_signed = current - allocated_signed
        if remaining_signed == Decimal("0"):
            cur.execute(
                """
                UPDATE journal_lines
                SET account_id = %s
                WHERE id = %s
                """,
                (cash_account_id, source_line_id),
            )
            return
        cur.execute(
            """
            UPDATE journal_lines
            SET amount = %s
            WHERE id = %s
            """,
            (remaining_signed, source_line_id),
        )
        cur.execute(
            """
            INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
            VALUES (%s, %s, %s, %s)
            """,
            (line["entry_id"], cash_account_id, line["party_id"], allocated_signed),
        )

    @staticmethod
    def _append_cash_and_unearned_lines(
        cur,
        entry_id: int,
        party_id: int,
        cash_account_id: int,
        unearned_account_id: int,
        unapplied: Decimal,
    ) -> None:
        cur.execute(
            """
            INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
            VALUES (%s, %s, %s, %s)
            """,
            (entry_id, cash_account_id, party_id, unapplied),
        )
        cur.execute(
            """
            INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
            VALUES (%s, %s, %s, %s)
            """,
            (entry_id, unearned_account_id, party_id, -unapplied),
        )

    @staticmethod
    def _validate_obligation_types_for_settlement(settlement_type: str, obligations) -> None:
        expected = "receivable" if settlement_type == "receipt" else "payable"
        for row in obligations:
            if row["obligation_type"] != expected:
                raise LedgerValidationError(f"{settlement_type} settlements require {expected} obligations")

    @staticmethod
    def _split_receipt_allocations(event_date: date, obligations, allocation_by_id) -> tuple[Decimal, Decimal]:
        due = Decimal("0")
        early = Decimal("0")
        for row in obligations:
            amount = allocation_by_id[row["id"]]
            source_date = row.get("source_entry_date")
            if source_date is not None and source_date > event_date:
                early += amount
            else:
                due += amount
        return due, early

    @staticmethod
    def _validate_allocation_amounts(allocations, obligations) -> None:
        open_by_id = {row["id"]: Decimal(row["open_amount"]) for row in obligations}
        for item in allocations:
            if item.amount > open_by_id[item.obligation_id]:
                raise LedgerValidationError("allocation amount cannot exceed obligation open amount")

    def _insert_settlement_journal_lines(
        self,
        cur,
        payload: SettlementWrite,
        settings,
        entry_id: int,
        allocated_total: Decimal,
        *,
        due_allocated: Decimal = Decimal("0"),
        early_allocated: Decimal = Decimal("0"),
    ) -> None:
        if payload.settlement_type == "receipt":
            ar_account_id = settings["accounts_receivable_account_id"]
            ur_account_id = settings["unearned_revenue_account_id"]
            lines = [(payload.cash_account_id, payload.party_id, payload.amount)]
            if due_allocated > Decimal("0"):
                lines.append((ar_account_id, payload.party_id, -due_allocated))
            unapplied = payload.amount - allocated_total
            ur_total = early_allocated + unapplied
            if ur_total > Decimal("0"):
                lines.append((ur_account_id, payload.party_id, -ur_total))
        else:
            ap_account_id = settings["accounts_payable_account_id"]
            lines = [
                (ap_account_id, payload.party_id, allocated_total),
                (payload.cash_account_id, payload.party_id, -payload.amount),
            ]
        for account_id, party_id, amount in lines:
            self._assert_account_active(cur, account_id)
            cur.execute(
                """
                INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
                VALUES (%s, %s, %s, %s)
                """,
                (entry_id, account_id, party_id, amount),
            )

    @staticmethod
    def _reclassify_receivable_line_to_unearned(
        cur,
        obligation_id: int,
        source_line_id: int,
        ar_account_id: int,
        unearned_account_id: int,
        allocation_amount: Decimal,
    ) -> None:
        cur.execute(
            """
            SELECT entry_id, party_id, amount
            FROM journal_lines
            WHERE id = %s
            FOR UPDATE
            """,
            (source_line_id,),
        )
        source_line = cur.fetchone()
        if not source_line:
            raise LedgerValidationError("obligation source line not found for early receipt reclassification")
        current_amount = Decimal(source_line["amount"])
        sign = Decimal("1") if current_amount >= Decimal("0") else Decimal("-1")
        moved_amount = sign * allocation_amount
        remaining_amount = current_amount - moved_amount
        if remaining_amount == Decimal("0"):
            cur.execute(
                """
                UPDATE journal_lines
                SET account_id = %s
                WHERE id = %s
                """,
                (unearned_account_id, source_line_id),
            )
            return
        cur.execute(
            """
            UPDATE journal_lines
            SET account_id = %s, amount = %s
            WHERE id = %s
            """,
            (unearned_account_id, moved_amount, source_line_id),
        )
        cur.execute(
            """
            INSERT INTO journal_lines (entry_id, account_id, party_id, amount)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                source_line["entry_id"],
                ar_account_id,
                source_line["party_id"],
                remaining_amount,
            ),
        )
        new_ar_line_id = cur.fetchone()["id"]
        cur.execute(
            """
            UPDATE accrual_obligations
            SET source_line_id = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (new_ar_line_id, obligation_id),
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

    def list_journal_entry_attachments(self, entry_id: int) -> list[JournalEntryAttachmentOut]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT id FROM journal_entries WHERE id = %s", (entry_id,))
                if not cur.fetchone():
                    raise LedgerNotFoundError(f"journal entry {entry_id} not found")
                cur.execute(
                    """
                    SELECT a.id, a.summary, a.external_reference, a.mime_type,
                           a.original_filename, a.created_at, a.updated_at
                    FROM attachments a
                    INNER JOIN journal_entry_attachments j ON j.attachment_id = a.id
                    WHERE j.journal_entry_id = %s
                    ORDER BY a.id ASC
                    """,
                    (entry_id,),
                )
                rows = cur.fetchall()
        return [JournalEntryAttachmentOut.model_validate(r) for r in rows]

    def add_journal_entry_attachment(
        self,
        entry_id: int,
        *,
        file_bytes: bytes,
        upload_filename: str | None,
        summary: str,
        external_reference: str | None,
    ) -> JournalEntryAttachmentOut:
        summary_clean = summary.strip()
        if not summary_clean:
            raise LedgerValidationError("attachment summary must not be blank")
        ext_ref: str | None
        if external_reference is not None and external_reference.strip():
            ext_ref = external_reference.strip()
        else:
            ext_ref = None
        original_name: str | None = None
        if upload_filename and upload_filename.strip():
            original_name = os.path.basename(upload_filename.strip()) or None
        if not file_bytes:
            raise LedgerValidationError("attachment file is empty")
        mime = detect_attachment_mime(file_bytes, original_name or upload_filename)

        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT id FROM journal_entries WHERE id = %s",
                        (entry_id,),
                    )
                    if not cur.fetchone():
                        raise LedgerNotFoundError(f"journal entry {entry_id} not found")
                    cur.execute(
                        "SELECT max_attachment_upload_bytes FROM ledger_settings WHERE id = 1",
                    )
                    lim_row = cur.fetchone()
                    if not lim_row:
                        raise LedgerValidationError("ledger settings row is missing")
                    max_b = int(lim_row["max_attachment_upload_bytes"])
                    if len(file_bytes) > max_b:
                        raise LedgerValidationError(
                            f"attachment exceeds maximum size of {max_b} bytes",
                        )
                    cur.execute(
                        """
                        INSERT INTO attachments (
                          blob, summary, external_reference, mime_type, original_filename
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id, summary, external_reference, mime_type,
                                  original_filename, created_at, updated_at
                        """,
                        (file_bytes, summary_clean, ext_ref, mime, original_name),
                    )
                    att = cur.fetchone()
                    assert att is not None
                    try:
                        cur.execute(
                            """
                            INSERT INTO journal_entry_attachments (journal_entry_id, attachment_id)
                            VALUES (%s, %s)
                            """,
                            (entry_id, att["id"]),
                        )
                    except errors.UniqueViolation as exc:
                        raise LedgerConflictError(
                            "this attachment is already linked to the journal entry",
                        ) from exc
        return JournalEntryAttachmentOut.model_validate(att)

    def get_journal_entry_attachment_download(
        self,
        entry_id: int,
        attachment_id: int,
    ) -> tuple[bytes, str, str]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT a.blob, a.mime_type, a.original_filename
                    FROM attachments a
                    INNER JOIN journal_entry_attachments j ON j.attachment_id = a.id
                    WHERE j.journal_entry_id = %s AND a.id = %s
                    """,
                    (entry_id, attachment_id),
                )
                row = cur.fetchone()
                if not row:
                    raise LedgerNotFoundError(
                        f"attachment {attachment_id} not found for journal entry {entry_id}",
                    )
        basename = self._attachment_download_basename(
            attachment_id,
            row["mime_type"],
            row["original_filename"],
        )
        return row["blob"], row["mime_type"], basename

    def unlink_journal_entry_attachment(self, entry_id: int, attachment_id: int) -> None:
        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM journal_entry_attachments
                        WHERE journal_entry_id = %s AND attachment_id = %s
                        """,
                        (entry_id, attachment_id),
                    )
                    if cur.rowcount == 0:
                        raise LedgerNotFoundError(
                            f"attachment {attachment_id} not linked to journal entry {entry_id}",
                        )

    @staticmethod
    def _attachment_download_basename(
        attachment_id: int,
        mime_type: str,
        original_filename: str | None,
    ) -> str:
        if original_filename and str(original_filename).strip():
            return os.path.basename(str(original_filename).strip())
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "application/pdf": ".pdf",
        }
        ext = ext_map.get(mime_type, "")
        return f"attachment-{attachment_id}{ext}"
