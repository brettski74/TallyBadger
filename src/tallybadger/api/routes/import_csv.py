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

from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_rule_set_service import (
    CelRuleSetNotFoundError,
    CelRuleSetService,
)
from tallybadger.import_templates.models import ImportTemplateColumn
from tallybadger.ledger.models import JournalEntryOut, JournalEntryWrite, JournalLineIn
from tallybadger.ledger.service import LedgerService, LedgerValidationError

router = APIRouter(prefix="", tags=["import-csv"])

_TOKEN_TO_STRPTIME = {
    "yyyy": "%Y",
    "mm": "%m",
    "dd": "%d",
    "HH": "%H",
    "MM": "%M",
    "ss": "%S",
}
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


def _friendly_format_to_strptime(date_format: str) -> str:
    result = date_format
    for token, directive in _TOKEN_TO_STRPTIME.items():
        result = result.replace(token, directive)
    return result


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
        fmt = _friendly_format_to_strptime(col.date_format or "")
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError as exc:
            raise ValueError(
                f"invalid {col.data_type} value '{raw}' for format '{col.date_format}'",
            ) from exc
        return parsed.date() if col.data_type == "date" else parsed
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


def _require_string(bag: dict[str, Any], key: str) -> str:
    value = bag.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _build_lines_from_simple(
    bag: dict[str, Any],
    account_ids: dict[str, int],
    party_ids: dict[str, int],
) -> list[JournalLineIn]:
    dr = _require_string(bag, "dr-account")
    cr = _require_string(bag, "cr-account")
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
    ]


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


def _bag_to_journal_entry(
    bag: dict[str, Any],
    account_ids: dict[str, int],
    party_ids: dict[str, int],
) -> JournalEntryWrite:
    entry_date = _to_entry_date(bag.get("date"))
    summary = _require_string(bag, "summary")
    description_value = bag.get("description")
    description = None if description_value is None else str(description_value).strip() or None
    has_simple = all(
        key in bag and bag.get(key) not in (None, "")
        for key in ("dr-account", "cr-account", "amount")
    )
    if has_simple:
        if "line" in bag and bag.get("line") not in (None, []):
            raise ValueError("do not provide both simple fields and line[]")
        lines = _build_lines_from_simple(bag, account_ids, party_ids)
    else:
        lines = _build_lines_from_array(bag, account_ids, party_ids)
    return JournalEntryWrite(
        entry_date=entry_date,
        summary=summary,
        description=description,
        lines=lines,
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
    party_ids = {p.name: p.id for p in parties if p.is_active}

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
            result = evaluate_cel(rule_set, bag)
            if result.dropped:
                dropped_rows += 1
                continue
            bag = result.attributes

        try:
            pending_entries.append(_bag_to_journal_entry(bag, account_ids, party_ids))
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

