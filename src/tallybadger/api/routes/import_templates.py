"""Persisted CSV import template CRUD (#38)."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from tallybadger.import_templates.models import ImportTemplateColumn
from tallybadger.import_templates.service import (
    ImportTemplateConflictError,
    ImportTemplateInvalidRuleSetError,
    ImportTemplateNotFoundError,
    ImportTemplateService,
    ImportTemplateStored,
)

router = APIRouter(prefix="", tags=["import-templates"])


def get_import_template_service() -> ImportTemplateService:
    return ImportTemplateService()


class ImportTemplateSummaryOut(BaseModel):
    id: int
    name: str
    updated_at: datetime


class ImportTemplateOut(BaseModel):
    id: int
    name: str
    has_header_row: bool
    columns: list[ImportTemplateColumn]
    cel_rule_set_id: int | None
    created_at: datetime
    updated_at: datetime


def _to_out(row: ImportTemplateStored) -> ImportTemplateOut:
    return ImportTemplateOut(
        id=row.id,
        name=row.name,
        has_header_row=row.has_header_row,
        columns=row.columns,
        cel_rule_set_id=row.cel_rule_set_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ImportTemplateCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    has_header_row: bool = False
    columns: list[ImportTemplateColumn] = Field(default_factory=list)
    cel_rule_set_id: int | None = None


class ImportTemplatePatchPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    has_header_row: bool | None = None
    columns: list[ImportTemplateColumn] | None = None
    cel_rule_set_id: int | None = None


@router.get("/import-templates", response_model=list[ImportTemplateSummaryOut])
def list_import_templates(
    service: Annotated[ImportTemplateService, Depends(get_import_template_service)],
) -> list[ImportTemplateSummaryOut]:
    items = service.list_templates()
    return [ImportTemplateSummaryOut(id=x.id, name=x.name, updated_at=x.updated_at) for x in items]


@router.post("/import-templates", response_model=ImportTemplateOut, status_code=status.HTTP_201_CREATED)
def create_import_template(
    payload: ImportTemplateCreatePayload,
    service: Annotated[ImportTemplateService, Depends(get_import_template_service)],
) -> ImportTemplateOut:
    try:
        row = service.create_template(
            payload.name,
            payload.has_header_row,
            payload.columns,
            cel_rule_set_id=payload.cel_rule_set_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except ImportTemplateConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ImportTemplateInvalidRuleSetError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _to_out(row)


@router.get("/import-templates/{template_id}", response_model=ImportTemplateOut)
def get_import_template(
    template_id: int,
    service: Annotated[ImportTemplateService, Depends(get_import_template_service)],
) -> ImportTemplateOut:
    try:
        row = service.get_template(template_id)
    except ImportTemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_out(row)


@router.patch("/import-templates/{template_id}", response_model=ImportTemplateOut)
def patch_import_template(
    template_id: int,
    payload: ImportTemplatePatchPayload,
    service: Annotated[ImportTemplateService, Depends(get_import_template_service)],
) -> ImportTemplateOut:
    patch: dict[str, Any] = payload.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="at least one field must be provided",
        )
    try:
        row = service.update_template(template_id, patch)
    except ImportTemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportTemplateConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ImportTemplateInvalidRuleSetError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _to_out(row)


@router.delete("/import-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import_template(
    template_id: int,
    service: Annotated[ImportTemplateService, Depends(get_import_template_service)],
) -> Response:
    try:
        service.delete_template(template_id)
    except ImportTemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
