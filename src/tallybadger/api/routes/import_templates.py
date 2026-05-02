"""Persisted CSV import template CRUD (#38)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator

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


ImportNormalBalance = Literal["debit", "credit"]


class ImportTemplateOut(BaseModel):
    id: int
    name: str
    has_header_row: bool
    columns: list[ImportTemplateColumn]
    cel_rule_set_id: int | None
    default_import_account_id: int | None
    default_import_normal_balance: ImportNormalBalance | None
    created_at: datetime
    updated_at: datetime


def _to_out(row: ImportTemplateStored) -> ImportTemplateOut:
    bal = row.default_import_normal_balance
    return ImportTemplateOut(
        id=row.id,
        name=row.name,
        has_header_row=row.has_header_row,
        columns=row.columns,
        cel_rule_set_id=row.cel_rule_set_id,
        default_import_account_id=row.default_import_account_id,
        default_import_normal_balance=bal if bal in ("debit", "credit") else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ImportTemplateCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    has_header_row: bool = False
    columns: list[ImportTemplateColumn] = Field(default_factory=list)
    cel_rule_set_id: int | None = None
    default_import_account_id: int | None = Field(default=None, gt=0)
    default_import_normal_balance: ImportNormalBalance | None = None

    @model_validator(mode="after")
    def default_import_pair(self) -> "ImportTemplateCreatePayload":
        if self.default_import_normal_balance is not None and self.default_import_account_id is None:
            raise ValueError("default_import_normal_balance requires default_import_account_id")
        return self


class ImportTemplatePatchPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    has_header_row: bool | None = None
    columns: list[ImportTemplateColumn] | None = None
    cel_rule_set_id: int | None = None
    default_import_account_id: int | None = None
    default_import_normal_balance: ImportNormalBalance | None = None

    @model_validator(mode="after")
    def patch_default_import_pair(self) -> "ImportTemplatePatchPayload":
        if self.default_import_normal_balance is not None and self.default_import_account_id is None:
            raise ValueError("default_import_normal_balance requires default_import_account_id")
        return self


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
            default_import_account_id=payload.default_import_account_id,
            default_import_normal_balance=payload.default_import_normal_balance,
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
        existing = service.get_template(template_id)
    except ImportTemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if patch.get("default_import_account_id") is None and "default_import_account_id" in patch:
        patch["default_import_normal_balance"] = None
    merged_account = existing.default_import_account_id
    merged_normal = existing.default_import_normal_balance
    if "default_import_account_id" in patch:
        merged_account = patch["default_import_account_id"]
    if "default_import_normal_balance" in patch:
        merged_normal = patch["default_import_normal_balance"]
    if merged_account is None:
        merged_normal = None
    if merged_normal is not None and merged_account is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="default_import_normal_balance requires default_import_account_id",
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
