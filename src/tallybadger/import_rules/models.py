from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

NumericCompareOp = Literal["lt", "lte", "eq", "gte", "gt"]
RegexFlagName = Literal["ignorecase", "multiline", "dotall"]


class RegexGroupRef(BaseModel):
    """Reference a capture group from the regex matcher at `matcher_index` within the same rule."""

    matcher_index: int = Field(ge=0)
    group: int | str = Field(
        description="1-based group index or named group; str keys must be non-empty",
    )

    @model_validator(mode="after")
    def _validate_group(self) -> RegexGroupRef:
        if isinstance(self.group, int) and self.group < 1:
            raise ValueError("numbered regex group must be >= 1")
        if isinstance(self.group, str) and not self.group.strip():
            raise ValueError("named regex group must be non-empty")
        return self


class SetAttributeAction(BaseModel):
    type: Literal["set_attribute"] = "set_attribute"
    name: str = Field(min_length=1)
    literal_value: str | None = None
    from_attribute: str | None = None
    from_regex_group: RegexGroupRef | None = None

    @model_validator(mode="after")
    def _one_source(self) -> SetAttributeAction:
        has_lit = self.literal_value is not None
        has_attr = self.from_attribute is not None
        has_rx = self.from_regex_group is not None
        if has_lit + has_attr + has_rx != 1:
            raise ValueError(
                "set_attribute requires exactly one of literal_value, from_attribute, from_regex_group",
            )
        return self


class AppendToAttributeAction(BaseModel):
    type: Literal["append_to_attribute"] = "append_to_attribute"
    name: str = Field(min_length=1)
    separator: str = " "
    literal_value: str | None = None
    from_attribute: str | None = None
    from_regex_group: RegexGroupRef | None = None

    @model_validator(mode="after")
    def _one_source(self) -> AppendToAttributeAction:
        has_lit = self.literal_value is not None
        has_attr = self.from_attribute is not None
        has_rx = self.from_regex_group is not None
        if has_lit + has_attr + has_rx != 1:
            raise ValueError(
                "append_to_attribute requires exactly one of literal_value, from_attribute, from_regex_group",
            )
        return self


class StopAction(BaseModel):
    type: Literal["stop"] = "stop"


class DropRowAction(BaseModel):
    type: Literal["drop_row"] = "drop_row"
    reason: str | None = Field(default=None, max_length=500)


class RequireReviewAction(BaseModel):
    type: Literal["require_review"] = "require_review"
    reason: str | None = Field(default=None, max_length=500)


Action = Annotated[
    SetAttributeAction
    | AppendToAttributeAction
    | StopAction
    | DropRowAction
    | RequireReviewAction,
    Field(discriminator="type"),
]


class RegexMatcher(BaseModel):
    type: Literal["regex"] = "regex"
    attribute: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    flags: list[RegexFlagName] = Field(default_factory=list)


class EqualsMatcher(BaseModel):
    type: Literal["equals"] = "equals"
    attribute: str = Field(min_length=1)
    value: str
    case_insensitive: bool = False


class NotEqualsMatcher(BaseModel):
    type: Literal["not_equals"] = "not_equals"
    attribute: str = Field(min_length=1)
    value: str
    case_insensitive: bool = False


class ContainsMatcher(BaseModel):
    type: Literal["contains"] = "contains"
    attribute: str = Field(min_length=1)
    substring: str
    case_insensitive: bool = False


class NumericCompareMatcher(BaseModel):
    type: Literal["numeric_compare"] = "numeric_compare"
    attribute: str = Field(min_length=1)
    op: NumericCompareOp
    value: str = Field(description="Compared using Decimal after stripping whitespace")


class InSetMatcher(BaseModel):
    type: Literal["in_set"] = "in_set"
    attribute: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)


class DayOfMonthMatcher(BaseModel):
    type: Literal["day_of_month"] = "day_of_month"
    attribute: str = Field(
        min_length=1,
        description="ISO date string (YYYY-MM-DD) after upstream normalization",
    )
    days: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _days_range(self) -> DayOfMonthMatcher:
        for d in self.days:
            if d < 1 or d > 31:
                raise ValueError("day_of_month days must be 1..31")
        return self


class DayOfWeekMatcher(BaseModel):
    type: Literal["day_of_week"] = "day_of_week"
    attribute: str = Field(min_length=1)
    weekdays: list[int] = Field(min_length=1, description="datetime.weekday(): Monday=0 .. Sunday=6")

    @model_validator(mode="after")
    def _wd_range(self) -> DayOfWeekMatcher:
        for w in self.weekdays:
            if w < 0 or w > 6:
                raise ValueError("weekdays must be 0..6 (Monday=0)")
        return self


Matcher = Annotated[
    RegexMatcher
    | EqualsMatcher
    | NotEqualsMatcher
    | ContainsMatcher
    | NumericCompareMatcher
    | InSetMatcher
    | DayOfMonthMatcher
    | DayOfWeekMatcher,
    Field(discriminator="type"),
]


class Rule(BaseModel):
    id: str | None = Field(default=None, max_length=120)
    name: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    sort_order: int = 0
    matchers: list[Matcher] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)


class RuleSet(BaseModel):
    rules: list[Rule] = Field(default_factory=list)


class TraceEvent(BaseModel):
    """Structured trace entry for debugging / test bench."""

    event: str
    detail: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    attributes: dict[str, str]
    dropped: bool = False
    drop_reason: str | None = None
    require_review: bool = False
    review_reason: str | None = None
    stopped_after_rule: str | None = None
    trace: list[TraceEvent] = Field(default_factory=list)
