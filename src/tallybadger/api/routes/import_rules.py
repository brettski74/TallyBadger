"""Stateless import rules evaluation API (issue #8; persistence in a follow-up)."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from tallybadger.import_rules.engine import evaluate
from tallybadger.import_rules.errors import ImportRulesError
from tallybadger.import_rules.models import EvaluationResult, RuleSet

router = APIRouter(prefix="", tags=["import-rules"])


class ImportRulesEvaluateRequest(BaseModel):
    """Bag from the import template: JSON numbers, strings, booleans, nulls, etc."""

    attributes: dict[str, Any] = Field(default_factory=dict)
    rule_set: RuleSet


@router.post("/import-rules/evaluate", response_model=EvaluationResult)
def evaluate_import_rules(payload: ImportRulesEvaluateRequest) -> EvaluationResult:
    try:
        return evaluate(payload.rule_set, payload.attributes)
    except ImportRulesError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
