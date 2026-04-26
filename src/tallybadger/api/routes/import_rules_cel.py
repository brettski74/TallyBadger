"""CEL-based rules spike API for issue #8."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import CelEvaluationResult, CelRuleSet
from tallybadger.import_rules.errors import ImportRulesCelError

router = APIRouter(prefix="", tags=["import-rules-cel"])


class ImportRulesCelEvaluateRequest(BaseModel):
    attributes: dict[str, Any] = Field(default_factory=dict)
    rule_set: CelRuleSet


@router.post("/import-rules/cel/evaluate", response_model=CelEvaluationResult)
def evaluate_import_rules_cel(payload: ImportRulesCelEvaluateRequest) -> CelEvaluationResult:
    try:
        return evaluate_cel(payload.rule_set, payload.attributes)
    except ImportRulesCelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
