from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status

from tallybadger.ledger.models import AccountCreate, AccountOut, JournalEntryOut, JournalEntryWrite
from tallybadger.ledger.service import (
    LedgerConflictError,
    LedgerNotFoundError,
    LedgerService,
    LedgerValidationError,
)

router = APIRouter(prefix="", tags=["ledger"])


@lru_cache
def get_ledger_service() -> LedgerService:
    return LedgerService()


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(service: LedgerService = Depends(get_ledger_service)) -> list[AccountOut]:
    return service.list_accounts()


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    service: LedgerService = Depends(get_ledger_service),
) -> AccountOut:
    try:
        return service.create_account(payload)
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/journal-entries",
    response_model=JournalEntryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_journal_entry(
    payload: JournalEntryWrite,
    service: LedgerService = Depends(get_ledger_service),
) -> JournalEntryOut:
    try:
        return service.create_entry(payload)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/journal-entries/{entry_id}", response_model=JournalEntryOut)
def get_journal_entry(
    entry_id: int,
    service: LedgerService = Depends(get_ledger_service),
) -> JournalEntryOut:
    try:
        return service.get_entry(entry_id)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/journal-entries/{entry_id}", response_model=JournalEntryOut)
def update_journal_entry(
    entry_id: int,
    payload: JournalEntryWrite,
    service: LedgerService = Depends(get_ledger_service),
) -> JournalEntryOut:
    try:
        return service.update_entry(entry_id, payload)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/journal-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_journal_entry(
    entry_id: int,
    service: LedgerService = Depends(get_ledger_service),
) -> None:
    try:
        service.delete_entry(entry_id)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
