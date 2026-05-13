"""Named journal-entry list filter presets (#107)."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from tallybadger.ledger.journal_entry_filter_preset_service import (
    JournalEntryFilterPresetConflictError,
    JournalEntryFilterPresetNotFoundError,
    JournalEntryFilterPresetService,
)
from tallybadger.ledger.models import (
    JournalEntryFilterPresetOut,
    JournalEntryFilterPresetPatch,
    JournalEntryFilterPresetWrite,
)

router = APIRouter(prefix="", tags=["journal-entry-filter-presets"])


@lru_cache
def get_journal_entry_filter_preset_service() -> JournalEntryFilterPresetService:
    return JournalEntryFilterPresetService()


@router.get(
    "/journal-entry-filter-presets",
    response_model=list[JournalEntryFilterPresetOut],
)
def list_journal_entry_filter_presets(
    service: Annotated[
        JournalEntryFilterPresetService,
        Depends(get_journal_entry_filter_preset_service),
    ],
) -> list[JournalEntryFilterPresetOut]:
    return service.list_presets()


@router.post(
    "/journal-entry-filter-presets",
    response_model=JournalEntryFilterPresetOut,
    status_code=status.HTTP_201_CREATED,
)
def create_journal_entry_filter_preset(
    payload: JournalEntryFilterPresetWrite,
    service: Annotated[
        JournalEntryFilterPresetService,
        Depends(get_journal_entry_filter_preset_service),
    ],
) -> JournalEntryFilterPresetOut:
    try:
        return service.create_preset(name=payload.name, definition=payload.definition)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except JournalEntryFilterPresetConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/journal-entry-filter-presets/{preset_id}",
    response_model=JournalEntryFilterPresetOut,
)
def get_journal_entry_filter_preset(
    preset_id: int,
    service: Annotated[
        JournalEntryFilterPresetService,
        Depends(get_journal_entry_filter_preset_service),
    ],
) -> JournalEntryFilterPresetOut:
    try:
        return service.get_preset(preset_id)
    except JournalEntryFilterPresetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.put(
    "/journal-entry-filter-presets/{preset_id}",
    response_model=JournalEntryFilterPresetOut,
)
def replace_journal_entry_filter_preset(
    preset_id: int,
    payload: JournalEntryFilterPresetWrite,
    service: Annotated[
        JournalEntryFilterPresetService,
        Depends(get_journal_entry_filter_preset_service),
    ],
) -> JournalEntryFilterPresetOut:
    try:
        return service.update_preset(
            preset_id,
            name=payload.name,
            definition=payload.definition,
        )
    except JournalEntryFilterPresetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except JournalEntryFilterPresetConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.patch(
    "/journal-entry-filter-presets/{preset_id}",
    response_model=JournalEntryFilterPresetOut,
)
def patch_journal_entry_filter_preset(
    preset_id: int,
    payload: JournalEntryFilterPresetPatch,
    service: Annotated[
        JournalEntryFilterPresetService,
        Depends(get_journal_entry_filter_preset_service),
    ],
) -> JournalEntryFilterPresetOut:
    try:
        return service.update_preset(
            preset_id,
            name=payload.name,
            definition=payload.definition,
        )
    except JournalEntryFilterPresetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except JournalEntryFilterPresetConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/journal-entry-filter-presets/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_journal_entry_filter_preset(
    preset_id: int,
    service: Annotated[
        JournalEntryFilterPresetService,
        Depends(get_journal_entry_filter_preset_service),
    ],
) -> Response:
    try:
        service.delete_preset(preset_id)
    except JournalEntryFilterPresetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
