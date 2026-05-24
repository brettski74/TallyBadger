"""Named cheque register list filter presets (#196)."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from tallybadger.ledger.cheque_register_filter_preset_service import (
    ChequeRegisterFilterPresetConflictError,
    ChequeRegisterFilterPresetNotFoundError,
    ChequeRegisterFilterPresetService,
)
from tallybadger.ledger.models import (
    ChequeRegisterFilterPresetOut,
    ChequeRegisterFilterPresetPatch,
    ChequeRegisterFilterPresetWrite,
)

router = APIRouter(prefix="", tags=["cheque-register-filter-presets"])


@lru_cache
def get_cheque_register_filter_preset_service() -> ChequeRegisterFilterPresetService:
    return ChequeRegisterFilterPresetService()


@router.get(
    "/cheque-register-filter-presets",
    response_model=list[ChequeRegisterFilterPresetOut],
)
def list_cheque_register_filter_presets(
    service: Annotated[
        ChequeRegisterFilterPresetService,
        Depends(get_cheque_register_filter_preset_service),
    ],
) -> list[ChequeRegisterFilterPresetOut]:
    return service.list_presets()


@router.post(
    "/cheque-register-filter-presets",
    response_model=ChequeRegisterFilterPresetOut,
    status_code=status.HTTP_201_CREATED,
)
def create_cheque_register_filter_preset(
    payload: ChequeRegisterFilterPresetWrite,
    service: Annotated[
        ChequeRegisterFilterPresetService,
        Depends(get_cheque_register_filter_preset_service),
    ],
) -> ChequeRegisterFilterPresetOut:
    try:
        return service.create_preset(name=payload.name, definition=payload.definition)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except ChequeRegisterFilterPresetConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/cheque-register-filter-presets/{preset_id}",
    response_model=ChequeRegisterFilterPresetOut,
)
def get_cheque_register_filter_preset(
    preset_id: int,
    service: Annotated[
        ChequeRegisterFilterPresetService,
        Depends(get_cheque_register_filter_preset_service),
    ],
) -> ChequeRegisterFilterPresetOut:
    try:
        return service.get_preset(preset_id)
    except ChequeRegisterFilterPresetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.put(
    "/cheque-register-filter-presets/{preset_id}",
    response_model=ChequeRegisterFilterPresetOut,
)
def replace_cheque_register_filter_preset(
    preset_id: int,
    payload: ChequeRegisterFilterPresetWrite,
    service: Annotated[
        ChequeRegisterFilterPresetService,
        Depends(get_cheque_register_filter_preset_service),
    ],
) -> ChequeRegisterFilterPresetOut:
    try:
        return service.update_preset(
            preset_id,
            name=payload.name,
            definition=payload.definition,
        )
    except ChequeRegisterFilterPresetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ChequeRegisterFilterPresetConflictError as exc:
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
    "/cheque-register-filter-presets/{preset_id}",
    response_model=ChequeRegisterFilterPresetOut,
)
def patch_cheque_register_filter_preset(
    preset_id: int,
    payload: ChequeRegisterFilterPresetPatch,
    service: Annotated[
        ChequeRegisterFilterPresetService,
        Depends(get_cheque_register_filter_preset_service),
    ],
) -> ChequeRegisterFilterPresetOut:
    try:
        return service.update_preset(
            preset_id,
            name=payload.name,
            definition=payload.definition,
        )
    except ChequeRegisterFilterPresetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ChequeRegisterFilterPresetConflictError as exc:
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
    "/cheque-register-filter-presets/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_cheque_register_filter_preset(
    preset_id: int,
    service: Annotated[
        ChequeRegisterFilterPresetService,
        Depends(get_cheque_register_filter_preset_service),
    ],
) -> Response:
    try:
        service.delete_preset(preset_id)
    except ChequeRegisterFilterPresetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
