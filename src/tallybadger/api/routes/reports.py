"""Read-only financial reports API."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.responses import Response

from tallybadger.api.income_expense_export import (
    income_expense_report_csv_bytes,
    income_expense_report_filename_stem,
    income_expense_report_pdf_bytes,
)
from tallybadger.ledger.income_expense_report import resolve_income_expense_preset
from tallybadger.ledger.models import IncomeExpenseReportOut
from tallybadger.ledger.service import LedgerService, LedgerValidationError

from .ledger import _attachment_content_disposition, get_ledger_service

router = APIRouter(prefix="/reports", tags=["reports"])

IncomeExpensePresetParam = Literal["current_year_to_date", "prior_full_year", "prior_year_to_date"]
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
        body = income_expense_report_pdf_bytes(report)
        media = "application/pdf"
        filename = f"{stem}.pdf"

    headers = {"Content-Disposition": _attachment_content_disposition(filename)}
    return Response(content=body, media_type=media, headers=headers)
