"""Compile-time validation for persisted CEL rule sets (#160)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from celpy import Environment

from tallybadger.import_rules.cel_engine import (
    _compile_regex_flags,
    _matcher_label,
    _rule_label,
    build_import_cel_functions,
)
from tallybadger.import_rules.cel_models import CelRegexCapture, CelRule, CelRuleSet
from tallybadger.import_rules.errors import ImportRulesCelError


@dataclass(frozen=True)
class CelRuleSetValidationIssue:
    rule_index: int
    rule_label: str
    field: str
    message: str
    capture_index: int | None = None
    matcher_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule_index": self.rule_index,
            "rule_label": self.rule_label,
            "field": self.field,
            "message": self.message,
        }
        if self.capture_index is not None:
            out["capture_index"] = self.capture_index
        if self.matcher_label is not None:
            out["matcher_label"] = self.matcher_label
        return out


class CelRuleSetValidationError(Exception):
    """Raised when one or more rules fail compile-time checks; carries every issue at once."""

    def __init__(self, issues: list[CelRuleSetValidationIssue]) -> None:
        self.issues = issues
        super().__init__(f"rule set validation failed ({len(issues)} error(s))")


def _validate_cel_expression(env: Environment, cel_functions: dict[str, Any], rule: CelRule, index: int) -> CelRuleSetValidationIssue | None:
    label = _rule_label(rule, index)
    try:
        ast = env.compile(rule.expression)
        env.program(ast, functions=cel_functions)
    except Exception as exc:
        return CelRuleSetValidationIssue(
            rule_index=index,
            rule_label=label,
            field="expression",
            message=str(exc),
        )
    return None


def _validate_capture_pattern(cap: CelRegexCapture, rule: CelRule, rule_index: int, capture_index: int) -> CelRuleSetValidationIssue | None:
    label = _rule_label(rule, rule_index)
    matcher = _matcher_label(cap)
    try:
        flags = _compile_regex_flags(cap.flags)
    except ImportRulesCelError as exc:
        return CelRuleSetValidationIssue(
            rule_index=rule_index,
            rule_label=label,
            field="pattern",
            message=str(exc),
            capture_index=capture_index,
            matcher_label=matcher,
        )
    try:
        re.compile(cap.pattern, flags)
    except re.error as exc:
        return CelRuleSetValidationIssue(
            rule_index=rule_index,
            rule_label=label,
            field="pattern",
            message=str(exc),
            capture_index=capture_index,
            matcher_label=matcher,
        )
    return None


def validate_cel_rule_set(rule_set: CelRuleSet) -> None:
    """Validate every rule expression and capture pattern; raise with all issues if any fail."""
    issues: list[CelRuleSetValidationIssue] = []
    env = Environment()
    cel_functions = build_import_cel_functions()

    for index, rule in enumerate(rule_set.rules):
        expr_issue = _validate_cel_expression(env, cel_functions, rule, index)
        if expr_issue is not None:
            issues.append(expr_issue)
        for capture_index, cap in enumerate(rule.captures):
            cap_issue = _validate_capture_pattern(cap, rule, index, capture_index)
            if cap_issue is not None:
                issues.append(cap_issue)

    if issues:
        raise CelRuleSetValidationError(issues)
