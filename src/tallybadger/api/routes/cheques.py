"""HTTP API for the cheque register (#90)."""

from fastapi import APIRouter, Depends, HTTPException, status

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.ledger.models import ChequeCreate, ChequeOut, ChequeUpdate
from tallybadger.ledger.service import (
    LedgerConflictError,
    LedgerNotFoundError,
    LedgerService,
    LedgerValidationError,
)

router = APIRouter(prefix="", tags=["cheques"])


@router.get("/cheques", response_model=list[ChequeOut])
def list_cheques(service: LedgerService = Depends(get_ledger_service)) -> list[ChequeOut]:
    return service.list_cheques()


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
