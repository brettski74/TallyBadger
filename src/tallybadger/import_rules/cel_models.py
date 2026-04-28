from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CelRegexCapture(BaseModel):
    """Ordered regex step: must match for the rule to proceed; feeds `match`/`matches` in CEL."""

    attribute: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    flags: list[str] = Field(default_factory=list, description="ignorecase, multiline, dotall")


class CelRule(BaseModel):
    id: str | None = Field(default=None, max_length=120)
    name: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    sort_order: int = 0
    expression: str = Field(min_length=1)
    captures: list[CelRegexCapture] = Field(default_factory=list)


class CelRuleSet(BaseModel):
    rules: list[CelRule] = Field(default_factory=list)


class CelTraceEvent(BaseModel):
    event: str
    detail: dict[str, Any] = Field(default_factory=dict)


class CelEvaluationResult(BaseModel):
    attributes: dict[str, Any]
    dropped: bool = False
    drop_reason: str | None = None
    require_review: bool = False
    review_reason: str | None = None
    stopped_after_rule: str | None = None
    trace: list[CelTraceEvent] = Field(default_factory=list)
