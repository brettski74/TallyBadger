"""HTTP API for the cheque register (#90)."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.ledger.models import (
    ChequeCreate,
    ChequeFilterOptionsResponse,
    ChequeListResponse,
    ChequeOut,
    ChequeSeriesCreate,
    ChequeSeriesPreviewOut,
    ChequeUpdate,
)
from tallybadger.ledger.service import (
    LedgerConflictError,
    LedgerNotFoundError,
    LedgerService,
    LedgerValidationError,
)

router = APIRouter(prefix="", tags=["cheques"])

ChequeListStatusParam = Literal["open", "cleared", "void", "all"]


@router.get("/cheques", response_model=ChequeListResponse)
def list_cheques(
    list_status: Annotated[
        ChequeListStatusParam | None,
        Query(
            alias="status",
            description=(
                "Filter by register status. Omitted or `all` returns cheques in any status. "
                "The register UI defaults to `open` client-side."
            ),
        ),
    ] = None,
    party_ids: Annotated[
        list[str] | None,
        Query(
            description=(
                "Repeat for each party filter. Positive integers are party ids; "
                "the literal token `null` matches cheques with no party."
            ),
        ),
    ] = None,
    credit_account_ids: Annotated[list[int] | None, Query()] = None,
    debit_account_ids: Annotated[list[int] | None, Query()] = None,
    issue_from_date: date | None = None,
    issue_to_date: date | None = None,
    cleared_from_date: date | None = None,
    cleared_to_date: date | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    summary: str | None = Query(
        default=None,
        description="Case-insensitive POSIX regular expression matched against summary.",
    ),
    sort: Annotated[
        list[str] | None,
        Query(
            description=(
                "Sort keys in priority order, each `field:asc` or `field:desc`. "
                "When omitted, sorts by issue_date descending then id descending."
            ),
        ),
    ] = None,
    service: LedgerService = Depends(get_ledger_service),
) -> ChequeListResponse:
    try:
        cheques = service.list_cheques(
            list_status=list_status,
            party_id_tokens=party_ids,
            credit_account_ids=credit_account_ids,
            debit_account_ids=debit_account_ids,
            issue_from_date=issue_from_date,
            issue_to_date=issue_to_date,
            cleared_from_date=cleared_from_date,
            cleared_to_date=cleared_to_date,
            min_amount=min_amount,
            max_amount=max_amount,
            summary_pattern=summary,
            sort_tokens=sort,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ChequeListResponse(cheques=cheques)


@router.get("/cheques/filter-options", response_model=ChequeFilterOptionsResponse)
def list_cheque_filter_options(
    service: LedgerService = Depends(get_ledger_service),
) -> ChequeFilterOptionsResponse:
    return service.list_cheque_filter_options()


@router.post("/cheques/series/preview", response_model=ChequeSeriesPreviewOut)
def preview_cheque_series(
    payload: ChequeSeriesCreate,
    service: LedgerService = Depends(get_ledger_service),
) -> ChequeSeriesPreviewOut:
    try:
        return service.preview_cheque_series(payload)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/cheques/series", response_model=list[ChequeOut], status_code=status.HTTP_201_CREATED)
def create_cheque_series(
    payload: ChequeSeriesCreate,
    service: LedgerService = Depends(get_ledger_service),
) -> list[ChequeOut]:
    try:
        return service.create_cheque_series(payload)
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/cheques", response_model=ChequeOut, status_code=status.HTTP_201_CREATED)
def create_cheque(
    payload: ChequeCreate,
    service: LedgerService = Depends(get_ledger_service),
) -> ChequeOut:
    try:
        return service.create_cheque(payload)
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cheques/{cheque_id}", response_model=ChequeOut)
def get_cheque(
    cheque_id: int,
    service: LedgerService = Depends(get_ledger_service),
) -> ChequeOut:
    try:
        return service.get_cheque(cheque_id)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/cheques/{cheque_id}", response_model=ChequeOut)
def update_cheque(
    cheque_id: int,
    payload: ChequeUpdate,
    service: LedgerService = Depends(get_ledger_service),
) -> ChequeOut:
    try:
        return service.update_cheque(cheque_id, payload)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
