"""Read-only financial reports API."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.responses import Response

from tallybadger.api.account_statement_export import (
    account_statement_report_csv_bytes,
    account_statement_report_filename_stem,
    account_statement_report_pdf_bytes,
)
from tallybadger.api.balance_sheet_export import (
    balance_sheet_report_csv_bytes,
    balance_sheet_report_filename_stem,
    balance_sheet_report_pdf_bytes,
)
from tallybadger.api.income_expense_export import (
    income_expense_report_csv_bytes,
    income_expense_report_filename_stem,
    income_expense_report_pdf_bytes,
)
from tallybadger.ledger.balance_sheet_report import resolve_balance_sheet_preset
from tallybadger.ledger.income_expense_report import resolve_income_expense_preset
from tallybadger.ledger.models import (
    AccountStatementReportOut,
    BalanceSheetReportOut,
    IncomeExpenseReportOut,
)
from tallybadger.ledger.service import LedgerNotFoundError, LedgerService, LedgerValidationError

from .ledger import _attachment_content_disposition, get_ledger_service

router = APIRouter(prefix="/reports", tags=["reports"])

IncomeExpensePresetParam = Literal["current_year_to_date", "prior_full_year", "prior_year_to_date"]
BalanceSheetPresetParam = Literal["today", "prior_year_end"]
ExportFormat = Literal["csv", "pdf"]


def _resolve_income_expense_dates(
    *,
    start_date: date | None,
    end_date: date | None,
    preset: IncomeExpensePresetParam | None,
    as_of_date: date | None,
) -> tuple[date, date, IncomeExpensePresetParam | None]:
    has_range = start_date is not None and end_date is not None
    has_partial_range = (start_date is None) ^ (end_date is None)
    if has_partial_range:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date and end_date must both be set when using an explicit range",
        )
    if preset is not None and has_range:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="do not pass preset together with start_date/end_date",
        )
    if preset is None and not has_range:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide either preset or both start_date and end_date",
        )
    if preset is not None:
        as_of = as_of_date or date.today()
        start, end = resolve_income_expense_preset(preset, as_of)
        return start, end, preset
    assert start_date is not None and end_date is not None
    return start_date, end_date, None


def _resolve_balance_sheet_as_of(
    *,
    as_of_date: date | None,
    preset: BalanceSheetPresetParam | None,
    preset_anchor_date: date | None,
) -> tuple[date, BalanceSheetPresetParam | None]:
    if as_of_date is not None and preset is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="do not pass preset together with as_of_date",
        )
    if preset is None and as_of_date is None:
        # Default to today to keep the endpoint convenient while still allowing explicit options.
        return date.today(), None
    if preset is not None:
        anchor = preset_anchor_date or date.today()
        return resolve_balance_sheet_preset(preset, anchor), preset
    assert as_of_date is not None
    return as_of_date, None


@router.get("/income-expense", response_model=IncomeExpenseReportOut)
def get_income_expense_report(
    start_date: date | None = None,
    end_date: date | None = None,
    preset: IncomeExpensePresetParam | None = None,
    as_of_date: date | None = Query(
        default=None,
        description="Anchor date for preset expansion; defaults to the server's calendar date (see PR notes).",
    ),
    exclude_zero_balance_accounts: bool = False,
    service: LedgerService = Depends(get_ledger_service),
) -> IncomeExpenseReportOut:
    try:
        s, e, preset_out = _resolve_income_expense_dates(
            start_date=start_date,
            end_date=end_date,
            preset=preset,
            as_of_date=as_of_date,
        )
        return service.income_expense_report(
            start_date=s,
            end_date=e,
            exclude_zero_balance_accounts=exclude_zero_balance_accounts,
            preset=preset_out,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/income-expense/export")
def export_income_expense_report(
    format: Annotated[ExportFormat, Query(description="Download format")],
    start_date: date | None = None,
    end_date: date | None = None,
    preset: IncomeExpensePresetParam | None = None,
    as_of_date: date | None = Query(default=None),
    exclude_zero_balance_accounts: bool = False,
    service: LedgerService = Depends(get_ledger_service),
) -> Response:
    try:
        s, e, preset_out = _resolve_income_expense_dates(
            start_date=start_date,
            end_date=end_date,
            preset=preset,
            as_of_date=as_of_date,
        )
        report = service.income_expense_report(
            start_date=s,
            end_date=e,
            exclude_zero_balance_accounts=exclude_zero_balance_accounts,
            preset=preset_out,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    stem = income_expense_report_filename_stem(report)
    if format == "csv":
        body = income_expense_report_csv_bytes(report)
        media = "text/csv; charset=utf-8"
        filename = f"{stem}.csv"
    else:
        pdf_page_size = service.get_ledger_settings().pdf_page_size
        body = income_expense_report_pdf_bytes(report, page_size=pdf_page_size)
        media = "application/pdf"
        filename = f"{stem}.pdf"

    headers = {"Content-Disposition": _attachment_content_disposition(filename)}
    return Response(content=body, media_type=media, headers=headers)


@router.get("/balance-sheet", response_model=BalanceSheetReportOut)
def get_balance_sheet_report(
    as_of_date: date | None = Query(default=None),
    preset: BalanceSheetPresetParam | None = Query(default=None),
    preset_anchor_date: date | None = Query(
        default=None,
        description="Optional anchor date for preset resolution; defaults to the server's calendar date.",
    ),
    exclude_requires_review: bool = False,
    service: LedgerService = Depends(get_ledger_service),
) -> BalanceSheetReportOut:
    try:
        as_of, preset_out = _resolve_balance_sheet_as_of(
            as_of_date=as_of_date,
            preset=preset,
            preset_anchor_date=preset_anchor_date,
        )
        return service.balance_sheet_report(
            as_of_date=as_of,
            exclude_requires_review=exclude_requires_review,
            preset=preset_out,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/balance-sheet/export")
def export_balance_sheet_report(
    format: Annotated[ExportFormat, Query(description="Download format")],
    as_of_date: date | None = Query(default=None),
    preset: BalanceSheetPresetParam | None = Query(default=None),
    preset_anchor_date: date | None = Query(default=None),
    exclude_requires_review: bool = False,
    service: LedgerService = Depends(get_ledger_service),
) -> Response:
    try:
        as_of, preset_out = _resolve_balance_sheet_as_of(
            as_of_date=as_of_date,
            preset=preset,
            preset_anchor_date=preset_anchor_date,
        )
        report = service.balance_sheet_report(
            as_of_date=as_of,
            exclude_requires_review=exclude_requires_review,
            preset=preset_out,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    stem = balance_sheet_report_filename_stem(report)
    if format == "csv":
        body = balance_sheet_report_csv_bytes(report)
        media = "text/csv; charset=utf-8"
        filename = f"{stem}.csv"
    else:
        pdf_page_size = service.get_ledger_settings().pdf_page_size
        body = balance_sheet_report_pdf_bytes(report, page_size=pdf_page_size)
        media = "application/pdf"
        filename = f"{stem}.pdf"
    headers = {"Content-Disposition": _attachment_content_disposition(filename)}
    return Response(content=body, media_type=media, headers=headers)


def _require_account_statement_dates(
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="account_id, start_date, and end_date are required",
        )
    return start_date, end_date


@router.get("/account-statement", response_model=AccountStatementReportOut)
def get_account_statement_report(
    account_id: Annotated[int, Query(description="Ledger account id for the statement")],
    start_date: date | None = None,
    end_date: date | None = None,
    service: LedgerService = Depends(get_ledger_service),
) -> AccountStatementReportOut:
    s, e = _require_account_statement_dates(start_date, end_date)
    try:
        return service.account_statement_report(account_id=account_id, start_date=s, end_date=e)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/account-statement/export")
def export_account_statement_report(
    format: Annotated[ExportFormat, Query(description="Download format")],
    account_id: Annotated[int, Query(description="Ledger account id for the statement")],
    start_date: date | None = None,
    end_date: date | None = None,
    service: LedgerService = Depends(get_ledger_service),
) -> Response:
    s, e = _require_account_statement_dates(start_date, end_date)
    try:
        report = service.account_statement_report(account_id=account_id, start_date=s, end_date=e)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    stem = account_statement_report_filename_stem(report)
    if format == "csv":
        body = account_statement_report_csv_bytes(report)
        media = "text/csv; charset=utf-8"
        filename = f"{stem}.csv"
    else:
        pdf_page_size = service.get_ledger_settings().pdf_page_size
        body = account_statement_report_pdf_bytes(report, page_size=pdf_page_size)
        media = "application/pdf"
        filename = f"{stem}.pdf"
    headers = {"Content-Disposition": _attachment_content_disposition(filename)}
    return Response(content=body, media_type=media, headers=headers)
