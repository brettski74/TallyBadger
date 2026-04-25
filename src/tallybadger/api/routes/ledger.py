from functools import lru_cache

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from tallybadger.ledger.models import (
    AccountCreate,
    AccountLedgerLineOut,
    AccountOut,
    AccountUpdate,
    JournalEntryListItem,
    JournalEntryOut,
    JournalEntryWrite,
)
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


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    payload: AccountUpdate,
    service: LedgerService = Depends(get_ledger_service),
) -> AccountOut:
    try:
        return service.update_account(account_id, payload)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/journal-entries", response_model=list[JournalEntryListItem])
def list_journal_entries(
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: LedgerService = Depends(get_ledger_service),
) -> list[JournalEntryListItem]:
    return service.list_entries(
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


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


@router.get("/accounts/{account_id}/lines", response_model=list[AccountLedgerLineOut])
def list_account_lines(
    account_id: int,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: LedgerService = Depends(get_ledger_service),
) -> list[AccountLedgerLineOut]:
    try:
        return service.list_account_lines(
            account_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
