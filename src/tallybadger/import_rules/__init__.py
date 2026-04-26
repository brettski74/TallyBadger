"""Import rules engine: ordered matchers/actions over a bag of attributes (issue #8)."""

from tallybadger.import_rules.engine import evaluate
from tallybadger.import_rules.errors import ImportRulesError
from tallybadger.import_rules.models import (
    Action,
    AppendToAttributeAction,
    DayOfMonthMatcher,
    DayOfWeekMatcher,
    DropRowAction,
    EqualsMatcher,
    EvaluationResult,
    InSetMatcher,
    Matcher,
    NotEqualsMatcher,
    NumericCompareMatcher,
    RegexMatcher,
    RegexGroupRef,
    RequireReviewAction,
    Rule,
    RuleSet,
    SetAttributeAction,
    StopAction,
    TraceEvent,
)

__all__ = [
    "Action",
    "AppendToAttributeAction",
    "DayOfMonthMatcher",
    "DayOfWeekMatcher",
    "DropRowAction",
    "EqualsMatcher",
    "EvaluationResult",
    "ImportRulesError",
    "InSetMatcher",
    "Matcher",
    "NotEqualsMatcher",
    "NumericCompareMatcher",
    "RegexGroupRef",
    "RegexMatcher",
    "RequireReviewAction",
    "Rule",
    "RuleSet",
    "SetAttributeAction",
    "StopAction",
    "TraceEvent",
    "evaluate",
]
