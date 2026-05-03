"""CEL-based rules spike API for issue #8."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import CelEvaluationResult, CelRuleSet
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.service import LedgerService

router = APIRouter(prefix="", tags=["import-rules-cel"])


class ImportRulesCelEvaluateRequest(BaseModel):
    attributes: dict[str, Any] = Field(default_factory=dict)
    rule_set: CelRuleSet


@router.post("/import-rules/cel/evaluate", response_model=CelEvaluationResult)
def evaluate_import_rules_cel(
    payload: ImportRulesCelEvaluateRequest,
    ledger_service: Annotated[LedgerService, Depends(get_ledger_service)],
) -> CelEvaluationResult:
    try:
        parties = ledger_service.list_parties()
        accounts = ledger_service.list_accounts()
        return evaluate_cel(
            payload.rule_set,
            payload.attributes,
            parties=parties,
            accounts=accounts,
        )
    except ImportRulesCelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
