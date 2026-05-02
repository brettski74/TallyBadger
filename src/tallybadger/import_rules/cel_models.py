from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CelRegexCapture(BaseModel):
    """Ordered regex step: must match for the rule to proceed; feeds `match`/`matches` in CEL."""

    attribute: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    flags: list[str] = Field(default_factory=list, description="ignorecase, multiline, dotall")
    label: str | None = Field(
        default=None,
        max_length=200,
        description="Human-readable matcher name for UI and traces.",
    )

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value


class CelRule(BaseModel):
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
