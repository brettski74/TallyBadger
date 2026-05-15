from functools import lru_cache

import io
from datetime import date
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from starlette.responses import StreamingResponse

from tallybadger.ledger.models import (
    AccountCreate,
    AccountLedgerLineOut,
    AccountOut,
    AccountUpdate,
    AccrualObligationOut,
    AccrualPlanCreate,
    AccrualPlanOut,
    AccrualPlanUpdate,
    AccrualPreviewItem,
    LedgerSettingsOut,
    LedgerSettingsUpdate,
    ObligationStatusUpdate,
    PartyCreate,
    PartyOut,
    PartyUpdate,
    JournalEntryAttachmentOut,
    JournalEntryListItem,
    JournalEntryOut,
    JournalEntryWrite,
    SettlementOut,
    SettlementWrite,
)
from tallybadger.ledger.service import (
    LedgerConflictError,
    LedgerNotFoundError,
    LedgerService,
    LedgerValidationError,
    read_upload_file_limited,
)

router = APIRouter(prefix="", tags=["ledger"])


def _attachment_content_disposition(filename: str) -> str:
    escaped = filename.replace("\\", "\\\\").replace('"', '\\"')
    utf8 = quote(filename, safe="")
    return f'attachment; filename="{escaped}"; filename*=UTF-8\'\'{utf8}'


@lru_cache
def get_ledger_service() -> LedgerService:
    return LedgerService()


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(service: LedgerService = Depends(get_ledger_service)) -> list[AccountOut]:
    return service.list_accounts()


@router.get("/parties", response_model=list[PartyOut])
def list_parties(service: LedgerService = Depends(get_ledger_service)) -> list[PartyOut]:
    return service.list_parties()


@router.get("/parties/subtype-suggestions", response_model=list[str])
def list_party_subtype_suggestions(service: LedgerService = Depends(get_ledger_service)) -> list[str]:
    return service.list_party_subtype_suggestions()


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    service: LedgerService = Depends(get_ledger_service),
) -> AccountOut:
    try:
        return service.create_account(payload)
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/parties", response_model=PartyOut, status_code=status.HTTP_201_CREATED)
def create_party(
    payload: PartyCreate,
    service: LedgerService = Depends(get_ledger_service),
) -> PartyOut:
    try:
        return service.create_party(payload)
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


@router.patch("/parties/{party_id}", response_model=PartyOut)
def update_party(
    party_id: int,
    payload: PartyUpdate,
    service: LedgerService = Depends(get_ledger_service),
) -> PartyOut:
    try:
        return service.update_party(party_id, payload)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/accrual-plans", response_model=list[AccrualPlanOut])
def list_accrual_plans(
    service: LedgerService = Depends(get_ledger_service),
) -> list[AccrualPlanOut]:
    return service.list_accrual_plans()


@router.post("/accrual-plans/preview", response_model=list[AccrualPreviewItem])
def preview_accrual_plan(
    payload: AccrualPlanCreate,
    service: LedgerService = Depends(get_ledger_service),
) -> list[AccrualPreviewItem]:
    try:
        return service.preview_accrual_plan(payload)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/accrual-plans",
    response_model=AccrualPlanOut,
    status_code=status.HTTP_201_CREATED,
)
def create_accrual_plan(
    payload: AccrualPlanCreate,
    service: LedgerService = Depends(get_ledger_service),
) -> AccrualPlanOut:
    try:
        return service.create_accrual_plan(payload)
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/accrual-plans/{plan_id}", response_model=AccrualPlanOut)
def update_accrual_plan(
    plan_id: int,
    payload: AccrualPlanUpdate,
    service: LedgerService = Depends(get_ledger_service),
) -> AccrualPlanOut:
    try:
        return service.update_accrual_plan(plan_id, payload)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/ledger-settings", response_model=LedgerSettingsOut)
def get_ledger_settings(service: LedgerService = Depends(get_ledger_service)) -> LedgerSettingsOut:
    return service.get_ledger_settings()


@router.patch("/ledger-settings", response_model=LedgerSettingsOut)
def update_ledger_settings(
    payload: LedgerSettingsUpdate,
    service: LedgerService = Depends(get_ledger_service),
) -> LedgerSettingsOut:
    try:
        return service.update_ledger_settings(payload)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/obligations/{party_id}", response_model=list[AccrualObligationOut])
def list_open_obligations(
    party_id: int,
    service: LedgerService = Depends(get_ledger_service),
) -> list[AccrualObligationOut]:
    return service.list_open_obligations(party_id)


@router.patch("/obligations/{obligation_id}/status", response_model=AccrualObligationOut)
def update_obligation_status(
    obligation_id: int,
    payload: ObligationStatusUpdate,
    service: LedgerService = Depends(get_ledger_service),
) -> AccrualObligationOut:
    try:
        return service.update_obligation_status(obligation_id, payload)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settlements", response_model=SettlementOut, status_code=status.HTTP_201_CREATED)
def create_settlement(
    payload: SettlementWrite,
    service: LedgerService = Depends(get_ledger_service),
) -> SettlementOut:
    try:
        return service.record_settlement(payload)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/journal-entries", response_model=list[JournalEntryListItem])
def list_journal_entries(
    from_date: date | None = None,
    to_date: date | None = None,
    needs_review: bool | None = None,
    account_ids: Annotated[list[int] | None, Query()] = None,
    party_ids: Annotated[list[int] | None, Query()] = None,
    accrual_plan_ids: Annotated[list[int] | None, Query()] = None,
    amount_low: int | None = Query(default=None, ge=0),
    amount_high: int | None = Query(default=None, ge=0),
    cheque_association: Literal["any", "with_cheque", "without_cheque"] = "any",
    import_batch_id: int | None = Query(default=None, gt=0),
    import_basename: str | None = Query(default=None, min_length=1, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: LedgerService = Depends(get_ledger_service),
) -> list[JournalEntryListItem]:
    try:
        return service.list_entries(
            from_date=from_date,
            to_date=to_date,
            needs_review=needs_review,
            account_ids=account_ids,
            party_ids=party_ids,
            accrual_plan_ids=accrual_plan_ids,
            amount_low=amount_low,
            amount_high=amount_high,
            cheque_association=cheque_association,
            import_batch_id=import_batch_id,
            import_basename=import_basename,
            limit=limit,
            offset=offset,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@router.delete(
    "/journal-entries/{entry_id}/review-messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_journal_entry_review_message(
    entry_id: int,
    message_id: int,
    service: LedgerService = Depends(get_ledger_service),
) -> None:
    try:
        service.delete_journal_entry_review_message(entry_id, message_id)
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


@router.get(
    "/journal-entries/{entry_id}/attachments",
    response_model=list[JournalEntryAttachmentOut],
)
def list_journal_entry_attachments(
    entry_id: int,
    service: LedgerService = Depends(get_ledger_service),
) -> list[JournalEntryAttachmentOut]:
    try:
        return service.list_journal_entry_attachments(entry_id)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/journal-entries/{entry_id}/attachments",
    response_model=JournalEntryAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_journal_entry_attachment(
    entry_id: int,
    service: LedgerService = Depends(get_ledger_service),
    file: UploadFile = File(...),
    summary: str = Form(...),
    external_reference: str | None = Form(default=None),
) -> JournalEntryAttachmentOut:
    try:
        settings = service.get_ledger_settings()
        raw = read_upload_file_limited(file.file, settings.max_attachment_upload_bytes)
        return service.add_journal_entry_attachment(
            entry_id,
            file_bytes=raw,
            upload_filename=file.filename,
            summary=summary,
            external_reference=external_reference,
        )
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LedgerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/journal-entries/{entry_id}/attachments/{attachment_id}")
def download_journal_entry_attachment(
    entry_id: int,
    attachment_id: int,
    service: LedgerService = Depends(get_ledger_service),
) -> StreamingResponse:
    try:
        blob, mime, basename = service.get_journal_entry_attachment_download(
            entry_id,
            attachment_id,
        )
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    headers = {"Content-Disposition": _attachment_content_disposition(basename)}
    return StreamingResponse(io.BytesIO(blob), media_type=mime, headers=headers)


@router.delete(
    "/journal-entries/{entry_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unlink_journal_entry_attachment(
    entry_id: int,
    attachment_id: int,
    service: LedgerService = Depends(get_ledger_service),
) -> None:
    try:
        service.unlink_journal_entry_attachment(entry_id, attachment_id)
    except LedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
