"""Persisted CEL rule set CRUD (#37)."""

from datetime import datetime
from typing import Annotated, Self

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator

from tallybadger.import_rules.cel_models import CelRuleSet
from tallybadger.import_rules.cel_rule_set_service import (
    CelRuleSetConflictError,
    CelRuleSetNotFoundError,
    CelRuleSetService,
    CelRuleSetStored,
)
from tallybadger.import_rules.cel_rule_set_validation import CelRuleSetValidationError

router = APIRouter(prefix="", tags=["import-rules-cel"])


def get_cel_rule_set_service() -> CelRuleSetService:
    return CelRuleSetService()


class CelRuleSetSummaryOut(BaseModel):
    id: int
    name: str
    updated_at: datetime


class CelRuleSetStoredOut(BaseModel):
    id: int
    name: str
    rule_set: CelRuleSet
    created_at: datetime
    updated_at: datetime


def _to_stored_out(row: CelRuleSetStored) -> CelRuleSetStoredOut:
    return CelRuleSetStoredOut(
        id=row.id,
        name=row.name,
        rule_set=row.rule_set,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class CelRuleSetCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rule_set: CelRuleSet


class CelRuleSetPatchPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    rule_set: CelRuleSet | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if self.name is None and self.rule_set is None:
            raise ValueError("at least one of name or rule_set must be provided")
        return self


@router.get("/import-rules/cel/rule-sets", response_model=list[CelRuleSetSummaryOut])
def list_cel_rule_sets(
    service: Annotated[CelRuleSetService, Depends(get_cel_rule_set_service)],
) -> list[CelRuleSetSummaryOut]:
    items = service.list_rule_sets()
    return [
        CelRuleSetSummaryOut(id=x.id, name=x.name, updated_at=x.updated_at) for x in items
    ]


@router.post(
    "/import-rules/cel/rule-sets",
    response_model=CelRuleSetStoredOut,
    status_code=status.HTTP_201_CREATED,
)
def create_cel_rule_set(
    payload: CelRuleSetCreatePayload,
    service: Annotated[CelRuleSetService, Depends(get_cel_rule_set_service)],
) -> CelRuleSetStoredOut:
    try:
        row = service.create_rule_set(payload.name, payload.rule_set)
    except CelRuleSetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Rule set validation failed",
                "errors": [issue.to_dict() for issue in exc.issues],
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except CelRuleSetConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_stored_out(row)


@router.get("/import-rules/cel/rule-sets/{rule_set_id}", response_model=CelRuleSetStoredOut)
def get_cel_rule_set(
    rule_set_id: int,
    service: Annotated[CelRuleSetService, Depends(get_cel_rule_set_service)],
) -> CelRuleSetStoredOut:
    try:
        row = service.get_rule_set(rule_set_id)
    except CelRuleSetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_stored_out(row)


@router.patch("/import-rules/cel/rule-sets/{rule_set_id}", response_model=CelRuleSetStoredOut)
def patch_cel_rule_set(
    rule_set_id: int,
    payload: CelRuleSetPatchPayload,
    service: Annotated[CelRuleSetService, Depends(get_cel_rule_set_service)],
) -> CelRuleSetStoredOut:
    try:
        row = service.update_rule_set(
            rule_set_id,
            name=payload.name,
            rule_set=payload.rule_set,
        )
    except CelRuleSetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CelRuleSetConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CelRuleSetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Rule set validation failed",
                "errors": [issue.to_dict() for issue in exc.issues],
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _to_stored_out(row)


@router.delete("/import-rules/cel/rule-sets/{rule_set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cel_rule_set(
    rule_set_id: int,
    service: Annotated[CelRuleSetService, Depends(get_cel_rule_set_service)],
) -> Response:
    try:
        service.delete_rule_set(rule_set_id)
    except CelRuleSetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
