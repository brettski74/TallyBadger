"""CSV import orchestration endpoint (#40 / #9)."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from tallybadger.import_dates import parse_import_date_string, parse_import_datetime_string
from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_rule_set_service import (
    CelRuleSetNotFoundError,
    CelRuleSetService,
)
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.import_templates.models import ImportTemplateColumn
from tallybadger.ledger.models import (
    AccountOut,
    JournalEntryOut,
    JournalEntryWrite,
    JournalLineIn,
    LedgerSettingsOut,
)
from tallybadger.ledger.service import LedgerService, LedgerValidationError

router = APIRouter(prefix="", tags=["import-csv"])

_CURRENCY_PREFIX_RE = re.compile(r"^[^\d+\-(]+")


def get_ledger_service() -> LedgerService:
    return LedgerService()


def get_cel_rule_set_service() -> CelRuleSetService:
    return CelRuleSetService()


class CsvImportExecuteRequest(BaseModel):
    csv_text: str = Field(min_length=1)
    has_header_row: bool = False
    columns: list[ImportTemplateColumn] = Field(default_factory=list)
    cel_rule_set_id: int | None = None


class CsvImportRowError(BaseModel):
    row_number: int
    errors: list[str]


class CsvImportExecuteResult(BaseModel):
    posted_entries: int
    dropped_rows: int = 0
    row_errors: list[CsvImportRowError] = Field(default_factory=list)
    entries: list[JournalEntryOut] = Field(default_factory=list)


def _parse_decimal_from_csv(raw: str) -> Decimal:
    s = raw.strip()
    if not s:
        raise ValueError("value is blank")
    sign = Decimal("1")
    if s.startswith("(") and s.endswith(")"):
        sign = Decimal("-1")
        s = s[1:-1].strip()
    s = _CURRENCY_PREFIX_RE.sub("", s)
    s = s.replace(",", "").strip()
    if not s:
        raise ValueError("value is blank")
    try:
        return sign * Decimal(s)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid numeric value '{raw}'") from exc


def _convert_cell(raw: str, col: ImportTemplateColumn) -> Any:
    text = raw.strip()
    if col.data_type == "string":
        return text
    if col.data_type == "numeric":
        if not text:
            return None
        return _parse_decimal_from_csv(text)
    if col.data_type in ("date", "datetime"):
        if not text:
            return None
        fmt = col.date_format or ""
        try:
            if col.data_type == "date":
                parsed = parse_import_date_string(text, fmt)
            else:
                parsed = parse_import_datetime_string(text, fmt)
        except ValueError as exc:
            raise ValueError(
                f"invalid {col.data_type} value '{raw}' for format '{col.date_format}'",
            ) from exc
        return parsed
    raise ValueError(f"unsupported data_type '{col.data_type}'")


def _to_entry_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("date is required")
        try:
            if "T" in s or " " in s:
                return datetime.fromisoformat(s).date()
            return date.fromisoformat(s)
        except ValueError as exc:
            raise ValueError("date must be an ISO date or datetime string") from exc
    raise ValueError("date must be a date/datetime/string")


def _to_decimal_any(value: Any, *, field: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        return _parse_decimal_from_csv(value)
    raise ValueError(f"{field} must be numeric")


def _truthy_rule_flag(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in ("true", "1", "yes", "y"):
        return True
    if isinstance(value, int) and value == 1:
        return True
    return False


def _require_string(bag: dict[str, Any], key: str) -> str:
    value = bag.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _resolve_unallocated_account_name(
    *,
    role: str,
    settings: LedgerSettingsOut,
    accounts_by_id: dict[int, AccountOut],
) -> str:
    account_id = (
        settings.unallocated_debits_account_id
        if role == "debit"
        else settings.unallocated_credits_account_id
    )
    label = "unallocated debits" if role == "debit" else "unallocated credits"
    if account_id is None:
        raise ValueError(
            f"{label} account is not configured in ledger settings; configure it under Configuration",
        )
    acct = accounts_by_id.get(account_id)
    if acct is None or not acct.is_active:
        raise ValueError(f"{label} account is missing or inactive")
    if acct.type != "suspense":
        raise ValueError(f"{label} account must be a suspense account")
    return acct.name


def _build_lines_from_simple(
    bag: dict[str, Any],
    account_ids: dict[str, int],
    party_ids: dict[str, int],
    *,
    ledger_settings: LedgerSettingsOut,
    accounts_by_id: dict[int, AccountOut],
) -> tuple[list[JournalLineIn], bool]:
    dr = str(bag.get("dr-account") or "").strip()
    cr = str(bag.get("cr-account") or "").strip()
    debit_defaulted = not dr
    credit_defaulted = not cr
    if debit_defaulted:
        dr = _resolve_unallocated_account_name(
            role="debit",
            settings=ledger_settings,
            accounts_by_id=accounts_by_id,
        )
    if credit_defaulted:
        cr = _resolve_unallocated_account_name(
            role="credit",
            settings=ledger_settings,
            accounts_by_id=accounts_by_id,
        )
    amount = _to_decimal_any(bag.get("amount"), field="amount")
    if amount <= Decimal("0"):
        raise ValueError("amount must be greater than zero")
    if dr not in account_ids:
        raise ValueError(f"unknown account '{dr}'")
    if cr not in account_ids:
        raise ValueError(f"unknown account '{cr}'")
    dr_party_name = str(bag.get("dr-party")).strip() if bag.get("dr-party") is not None else ""
    cr_party_name = str(bag.get("cr-party")).strip() if bag.get("cr-party") is not None else ""
    if dr_party_name and dr_party_name not in party_ids:
        raise ValueError(f"unknown party '{dr_party_name}'")
    if cr_party_name and cr_party_name not in party_ids:
        raise ValueError(f"unknown party '{cr_party_name}'")
    defaulted_to_unallocated = debit_defaulted or credit_defaulted
    return [
        JournalLineIn(
            account_id=account_ids[dr],
            party_id=party_ids.get(dr_party_name) if dr_party_name else None,
            amount=amount,
        ),
        JournalLineIn(
            account_id=account_ids[cr],
            party_id=party_ids.get(cr_party_name) if cr_party_name else None,
            amount=-amount,
        ),
    ], defaulted_to_unallocated


def _build_lines_from_array(
    bag: dict[str, Any],
    account_ids: dict[str, int],
    party_ids: dict[str, int],
) -> list[JournalLineIn]:
    raw = bag.get("line")
    if not isinstance(raw, list):
        raise ValueError(
            "either simple fields (dr-account/cr-account/amount) or line[] is required",
        )
    if len(raw) < 2:
        raise ValueError("line must contain at least two rows")
    lines: list[JournalLineIn] = []
    total = Decimal("0")
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"line[{idx}] must be an object")
        account_name = str(item.get("account", "")).strip()
        if not account_name:
            raise ValueError(f"line[{idx}] account is required")
        if account_name not in account_ids:
            raise ValueError(f"unknown account '{account_name}'")
        amount = _to_decimal_any(item.get("amount"), field=f"line[{idx}].amount")
        if amount == Decimal("0"):
            raise ValueError(f"line[{idx}] amount must be non-zero")
        party_name = str(item.get("party")).strip() if item.get("party") is not None else ""
        if party_name and party_name not in party_ids:
            raise ValueError(f"unknown party '{party_name}'")
        lines.append(
            JournalLineIn(
                account_id=account_ids[account_name],
                party_id=party_ids.get(party_name) if party_name else None,
                amount=amount,
            ),
        )
        total += amount
    if total != Decimal("0"):
        raise ValueError("line amounts must balance to zero")
    return lines


def _has_nonempty_line_array(bag: dict[str, Any]) -> bool:
    raw = bag.get("line")
    return isinstance(raw, list) and len(raw) > 0


def _has_simple_amount(bag: dict[str, Any]) -> bool:
    return bag.get("amount") not in (None, "")


def _bag_to_journal_entry(
    bag: dict[str, Any],
    account_ids: dict[str, int],
    party_ids: dict[str, int],
    *,
    ledger_settings: LedgerSettingsOut,
    accounts_by_id: dict[int, AccountOut],
) -> JournalEntryWrite:
    entry_date = _to_entry_date(bag.get("date"))
    summary = _require_string(bag, "summary")
    description_value = bag.get("description")
    description = None if description_value is None else str(description_value).strip() or None
    has_line = _has_nonempty_line_array(bag)
    has_amount = _has_simple_amount(bag)
    if has_line and has_amount:
        raise ValueError("do not provide both amount and line[]")
    if has_line:
        lines = _build_lines_from_array(bag, account_ids, party_ids)
        requires_review = _truthy_rule_flag(bag.get("require_review"))
    elif has_amount:
        lines, defaulted_unallocated = _build_lines_from_simple(
            bag,
            account_ids,
            party_ids,
            ledger_settings=ledger_settings,
            accounts_by_id=accounts_by_id,
        )
        requires_review = defaulted_unallocated or _truthy_rule_flag(bag.get("require_review"))
    else:
        raise ValueError(
            "either amount (with optional dr-account/cr-account) or line[] is required",
        )
    return JournalEntryWrite(
        entry_date=entry_date,
        summary=summary,
        description=description,
        lines=lines,
        requires_review=requires_review,
    )


@router.post("/imports/csv/execute", response_model=CsvImportExecuteResult)
def execute_csv_import(
    payload: CsvImportExecuteRequest,
    ledger_service: Annotated[LedgerService, Depends(get_ledger_service)],
    cel_rule_set_service: Annotated[CelRuleSetService, Depends(get_cel_rule_set_service)],
) -> CsvImportExecuteResult:
    rule_set = None
    if payload.cel_rule_set_id is not None:
        try:
            rule_set = cel_rule_set_service.get_rule_set(payload.cel_rule_set_id).rule_set
        except CelRuleSetNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    accounts = ledger_service.list_accounts()
    parties = ledger_service.list_parties()
    account_ids = {a.name: a.id for a in accounts if a.is_active}
    accounts_by_id = {a.id: a for a in accounts}
    party_ids = {p.name: p.id for p in parties if p.is_active}
    try:
        ledger_settings = ledger_service.get_ledger_settings()
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    rows = list(csv.reader(io.StringIO(payload.csv_text)))
    if not rows:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="CSV has no rows")
    data_rows = rows[1:] if payload.has_header_row else rows

    pending_entries: list[JournalEntryWrite] = []
    row_errors: list[CsvImportRowError] = []
    dropped_rows = 0
    start_row_number = 2 if payload.has_header_row else 1

    for idx, row in enumerate(data_rows, start=start_row_number):
        errors: list[str] = []
        bag: dict[str, Any] = {}
        for col_index, col in enumerate(payload.columns):
            if not col.attribute_name:
                continue
            raw = row[col_index] if col_index < len(row) else ""
            try:
                bag[col.attribute_name] = _convert_cell(raw, col)
            except ValueError as exc:
                errors.append(str(exc))

        if errors:
            row_errors.append(CsvImportRowError(row_number=idx, errors=errors))
            continue

        if rule_set is not None:
            try:
                result = evaluate_cel(rule_set, bag)
            except ImportRulesCelError as exc:
                row_errors.append(CsvImportRowError(row_number=idx, errors=[str(exc)]))
                continue
            if result.dropped:
                dropped_rows += 1
                continue
            bag = result.attributes

        try:
            pending_entries.append(
                _bag_to_journal_entry(
                    bag,
                    account_ids,
                    party_ids,
                    ledger_settings=ledger_settings,
                    accounts_by_id=accounts_by_id,
                ),
            )
        except (ValueError, LedgerValidationError) as exc:
            row_errors.append(CsvImportRowError(row_number=idx, errors=[str(exc)]))

    if row_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "CSV import failed validation",
                "row_errors": [item.model_dump() for item in row_errors],
            },
        )

    try:
        created = ledger_service.create_entries_batch(pending_entries)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return CsvImportExecuteResult(
        posted_entries=len(created),
        dropped_rows=dropped_rows,
        entries=created,
    )

