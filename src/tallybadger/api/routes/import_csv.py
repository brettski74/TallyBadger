"""CSV import orchestration endpoint (#40 / #9)."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import PurePath
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from tallybadger.import_dates import parse_import_date_string, parse_import_datetime_string
from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import CelDebugEvent
from tallybadger.import_rules.cel_rule_set_service import (
    CelRuleSetNotFoundError,
    CelRuleSetService,
)
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.import_templates.models import ImportTemplateColumn
from tallybadger.ledger.models import (
    AccountOut,
    ImportBatchListItem,
    JournalEntryOut,
    JournalEntryWrite,
    JournalLineIn,
    LedgerSettingsOut,
)
from tallybadger.ledger.service import (
    LedgerDuplicateImportContentError,
    LedgerImportBasenameConflictError,
    LedgerService,
    LedgerValidationError,
)

router = APIRouter(prefix="", tags=["import-csv"])

_CURRENCY_PREFIX_RE = re.compile(r"^[^\d+\-(]+")


def get_ledger_service() -> LedgerService:
    return LedgerService()


def get_cel_rule_set_service() -> CelRuleSetService:
    return CelRuleSetService()


ImportNormalBalance = Literal["debit", "credit"]


class CsvImportExecuteRequest(BaseModel):
    csv_text: str = Field(min_length=1)
    basename: str = Field(min_length=1, max_length=512)
    confirm_duplicate_content: bool = False
    has_header_row: bool = False
    columns: list[ImportTemplateColumn] = Field(default_factory=list)
    cel_rule_set_id: int | None = None
    default_import_account_id: int | None = Field(default=None, gt=0)
    default_import_normal_balance: ImportNormalBalance | None = None

    @field_validator("basename", mode="before")
    @classmethod
    def _normalize_basename(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("basename must be a string")
        base = PurePath(value.strip()).name.strip()
        if not base:
            raise ValueError("basename must be non-empty")
        return base

    @model_validator(mode="after")
    def default_import_pair(self) -> "CsvImportExecuteRequest":
        if self.default_import_normal_balance is not None and self.default_import_account_id is None:
            raise ValueError("default_import_normal_balance requires default_import_account_id")
        return self


def _drop_empty_debug_field(data: dict[str, Any]) -> dict[str, Any]:
    """Omit ``debug`` when absent or empty (same JSON shape as successful ``entries[]`` rows)."""
    dbg = data.get("debug")
    if dbg is None or (isinstance(dbg, list) and len(dbg) == 0):
        data.pop("debug", None)
    return data


class CsvImportRowError(BaseModel):
    """422 row payload; optional CEL ``debug`` matches what that row would get in ``entries[]`` (#57)."""

    row_number: int
    errors: list[str]
    debug: list[CelDebugEvent] | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        return _drop_empty_debug_field(handler(self))


class CsvJournalEntryOut(JournalEntryOut):
    """CSV execute response row: same as ``JournalEntryOut`` plus optional CEL ``debug`` (#59)."""

    model_config = ConfigDict(from_attributes=True)

    debug: list[CelDebugEvent] | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        return _drop_empty_debug_field(handler(self))


class CsvImportExecuteResult(BaseModel):
    posted_entries: int
    dropped_rows: int = 0
    row_errors: list[CsvImportRowError] = Field(default_factory=list)
    entries: list[CsvJournalEntryOut] = Field(default_factory=list)
    import_batch_id: int | None = None
    basename: str | None = Field(
        default=None,
        description="Normalized CSV filename for the batch when import_batch_id is set (#136).",
    )


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


def _infer_normal_from_account_type(account_type: str) -> str:
    if account_type in ("asset", "expense", "suspense"):
        return "debit"
    return "credit"


def _default_import_account_name(
    account_id: int,
    accounts_by_id: dict[int, AccountOut],
) -> str:
    acct = accounts_by_id.get(account_id)
    if acct is None or not acct.is_active:
        raise ValueError("default import account is missing or inactive")
    return acct.name


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


def _optional_cheque_id_from_bag(bag: dict[str, Any]) -> int | None:
    """Read ``cheque-id`` from the attribute bag (CEL / column mapping); ``None`` when absent."""
    raw = bag.get("cheque-id")
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ValueError("cheque-id must be an integer")
    if isinstance(raw, int):
        if raw <= 0:
            raise ValueError("cheque-id must be positive")
        return raw
    if isinstance(raw, float):
        if not raw.is_integer():
            raise ValueError("cheque-id must be an integer")
        n = int(raw)
        if n <= 0:
            raise ValueError("cheque-id must be positive")
        return n
    if isinstance(raw, Decimal):
        if raw % 1 != 0:
            raise ValueError("cheque-id must be an integer")
        n = int(raw)
        if n <= 0:
            raise ValueError("cheque-id must be positive")
        return n
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            n = int(s)
        except ValueError as exc:
            raise ValueError(f"invalid cheque-id: {raw!r}") from exc
        if n <= 0:
            raise ValueError("cheque-id must be positive")
        return n
    raise ValueError(f"cheque-id has unsupported type: {type(raw).__name__}")


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
    default_import_account_id: int | None = None,
    default_import_normal_balance: str | None = None,
) -> tuple[list[JournalLineIn], bool, bool, bool]:
    dr = str(bag.get("dr-account") or "").strip()
    cr = str(bag.get("cr-account") or "").strip()

    signed = _to_decimal_any(bag.get("amount"), field="amount")
    if signed == Decimal("0"):
        raise ValueError("amount must be non-zero")
    mag = abs(signed)

    default_name: str | None = None
    normal: str | None = None
    if default_import_account_id is not None:
        default_name = _default_import_account_name(default_import_account_id, accounts_by_id)
        if default_import_normal_balance in ("debit", "credit"):
            normal = default_import_normal_balance
        else:
            normal = _infer_normal_from_account_type(
                accounts_by_id[default_import_account_id].type,
            )

    if default_name and normal:
        debit_normal = normal == "debit"
        default_on_debit = (signed > Decimal("0")) == debit_normal
        if default_on_debit and not dr:
            dr = default_name
        elif not default_on_debit and not cr:
            cr = default_name

    used_unalloc_dr = False
    used_unalloc_cr = False
    if not dr:
        dr = _resolve_unallocated_account_name(
            role="debit",
            settings=ledger_settings,
            accounts_by_id=accounts_by_id,
        )
        used_unalloc_dr = True
    if not cr:
        cr = _resolve_unallocated_account_name(
            role="credit",
            settings=ledger_settings,
            accounts_by_id=accounts_by_id,
        )
        used_unalloc_cr = True

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
    defaulted_to_unallocated = used_unalloc_dr or used_unalloc_cr
    return (
        [
            JournalLineIn(
                account_id=account_ids[dr],
                party_id=party_ids.get(dr_party_name) if dr_party_name else None,
                amount=mag,
            ),
            JournalLineIn(
                account_id=account_ids[cr],
                party_id=party_ids.get(cr_party_name) if cr_party_name else None,
                amount=-mag,
            ),
        ],
        defaulted_to_unallocated,
        used_unalloc_dr,
        used_unalloc_cr,
    )


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
    cel_review_messages: list[str] | None = None,
    default_import_account_id: int | None = None,
    default_import_normal_balance: str | None = None,
) -> JournalEntryWrite:
    entry_date = _to_entry_date(bag.get("date"))
    summary = _require_string(bag, "summary")
    description_value = bag.get("description")
    description = None if description_value is None else str(description_value).strip() or None
    has_line = _has_nonempty_line_array(bag)
    has_amount = _has_simple_amount(bag)
    review_messages: list[str] = list(cel_review_messages or [])
    if has_line and has_amount:
        raise ValueError("do not provide both amount and line[]")
    if has_line:
        lines = _build_lines_from_array(bag, account_ids, party_ids)
        if _truthy_rule_flag(bag.get("require_review")):
            review_messages.append(
                "This entry was flagged for review by an import rule or column mapping.",
            )
    elif has_amount:
        lines, _defaulted_unallocated, used_unalloc_dr, used_unalloc_cr = _build_lines_from_simple(
            bag,
            account_ids,
            party_ids,
            ledger_settings=ledger_settings,
            accounts_by_id=accounts_by_id,
            default_import_account_id=default_import_account_id,
            default_import_normal_balance=default_import_normal_balance,
        )
        if used_unalloc_dr:
            review_messages.append("The debit amount is unallocated.")
        if used_unalloc_cr:
            review_messages.append("The credit amount is unallocated.")
        if _truthy_rule_flag(bag.get("require_review")):
            review_messages.append(
                "This entry was flagged for review by an import rule or column mapping.",
            )
    else:
        raise ValueError(
            "either amount (with optional dr-account/cr-account) or line[] is required",
        )
    cheque_id = _optional_cheque_id_from_bag(bag)
    requires_review = len(review_messages) > 0
    return JournalEntryWrite(
        entry_date=entry_date,
        summary=summary,
        description=description,
        lines=lines,
        requires_review=requires_review,
        review_messages=review_messages,
        cheque_id=cheque_id,
    )


@router.get("/import-batches", response_model=list[ImportBatchListItem])
def list_import_batches(
    limit: int = Query(default=200, ge=1, le=500),
    ledger_service: LedgerService = Depends(get_ledger_service),
) -> list[ImportBatchListItem]:
    try:
        return ledger_service.list_import_batches(limit=limit)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


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
    open_cheques = ledger_service.list_cheques(list_status="open")
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
    pending_row_debug: list[list[CelDebugEvent] | None] = []
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

        default_account_for_cel: str | None = None
        if payload.default_import_account_id is not None and "default-account" not in bag:
            try:
                default_account_for_cel = _default_import_account_name(
                    payload.default_import_account_id,
                    accounts_by_id,
                )
            except ValueError as exc:
                row_errors.append(CsvImportRowError(row_number=idx, errors=[str(exc)]))
                continue

        row_debug: list[CelDebugEvent] | None = None
        if rule_set is not None:
            try:
                result = evaluate_cel(
                    rule_set,
                    bag,
                    parties=ledger_service.list_parties(),
                    accounts=accounts,
                    cheques=open_cheques,
                    row_number=idx,
                    default_account_name=default_account_for_cel,
                )
            except ImportRulesCelError as exc:
                row_errors.append(CsvImportRowError(row_number=idx, errors=[str(exc)]))
                continue
            if result.dropped:
                dropped_rows += 1
                continue
            bag = result.attributes
            bag.pop("review", None)
            bag.pop("review-messages", None)
            row_debug = list(result.debug) if result.debug else None
            cel_msgs = list(result.review_messages)
        else:
            cel_msgs = []

        try:
            pending_entries.append(
                _bag_to_journal_entry(
                    bag,
                    account_ids,
                    party_ids,
                    ledger_settings=ledger_settings,
                    accounts_by_id=accounts_by_id,
                    cel_review_messages=cel_msgs,
                    default_import_account_id=payload.default_import_account_id,
                    default_import_normal_balance=payload.default_import_normal_balance,
                ),
            )
            pending_row_debug.append(row_debug)
        except (ValueError, LedgerValidationError) as exc:
            row_errors.append(
                CsvImportRowError(row_number=idx, errors=[str(exc)], debug=row_debug),
            )

    if row_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "CSV import failed validation",
                "row_errors": [item.model_dump(mode="json") for item in row_errors],
            },
        )

    if not pending_entries:
        return CsvImportExecuteResult(
            posted_entries=0,
            dropped_rows=dropped_rows,
            row_errors=[],
            entries=[],
            import_batch_id=None,
            basename=None,
        )

    content_sha256 = hashlib.sha256(payload.csv_text.encode("utf-8")).digest()

    try:
        batch_id, created = ledger_service.create_import_batch_with_entries(
            basename=payload.basename,
            content_sha256=content_sha256,
            payloads=pending_entries,
            confirm_duplicate_content=payload.confirm_duplicate_content,
        )
    except LedgerDuplicateImportContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_import_content",
                "message": str(exc),
            },
        ) from exc
    except LedgerImportBasenameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "import_basename_conflict",
                "message": str(exc),
            },
        ) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    entries_out: list[CsvJournalEntryOut] = []
    for entry, dbg in zip(created, pending_row_debug, strict=True):
        if dbg:
            entries_out.append(CsvJournalEntryOut.model_validate({**entry.model_dump(), "debug": dbg}))
        else:
            entries_out.append(CsvJournalEntryOut.model_validate(entry.model_dump()))

    return CsvImportExecuteResult(
        posted_entries=len(created),
        dropped_rows=dropped_rows,
        entries=entries_out,
        import_batch_id=batch_id,
        basename=payload.basename,
    )

