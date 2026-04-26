"""Import rules engine: ordered matchers/actions over a bag of attributes (issue #8)."""

from tallybadger.import_rules.engine import evaluate
from tallybadger.import_rules.errors import ImportRulesCelError, ImportRulesError
from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import (
    CelEvaluationResult,
    CelRegexCapture,
    CelRule,
    CelRuleSet,
    CelTraceEvent,
)
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
    "CelEvaluationResult",
    "CelRegexCapture",
    "CelRule",
    "CelRuleSet",
    "CelTraceEvent",
    "EqualsMatcher",
    "ImportRulesCelError",
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
    "evaluate_cel",
]
