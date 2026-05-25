"""Unit tests: compile-time CEL rule set validation (#160)."""

from __future__ import annotations

import pytest

from tallybadger.import_rules.cel_models import CelRegexCapture, CelRule, CelRuleSet
from tallybadger.import_rules.cel_rule_set_validation import (
    CelRuleSetValidationError,
    validate_cel_rule_set,
)


def test_validate_collects_multiple_errors() -> None:
    rule_set = CelRuleSet(
        rules=[
            CelRule(expression="1 + ", captures=[]),
            CelRule(
                expression="null",
                captures=[CelRegexCapture(attribute="description", pattern="[unclosed", flags=[])],
            ),
        ],
    )
    with pytest.raises(CelRuleSetValidationError) as exc_info:
        validate_cel_rule_set(rule_set)
    issues = exc_info.value.issues
    assert len(issues) >= 2
    fields = {i.field for i in issues}
    assert "expression" in fields
    assert "pattern" in fields
    rule_indices = {i.rule_index for i in issues}
    assert 0 in rule_indices
    assert 1 in rule_indices


def test_validate_disabled_rule_with_bad_cel() -> None:
    rule_set = CelRuleSet(rules=[CelRule(enabled=False, expression="!!!", captures=[])])
    with pytest.raises(CelRuleSetValidationError) as exc_info:
        validate_cel_rule_set(rule_set)
    assert len(exc_info.value.issues) == 1
    assert exc_info.value.issues[0].field == "expression"
    assert exc_info.value.issues[0].rule_index == 0


def test_validate_named_rule_label_in_issue() -> None:
    rule_set = CelRuleSet(rules=[CelRule(name="My rule", expression="1 + ", captures=[])])
    with pytest.raises(CelRuleSetValidationError) as exc_info:
        validate_cel_rule_set(rule_set)
    assert exc_info.value.issues[0].rule_label == "My rule"


def test_validate_matcher_label_on_pattern_error() -> None:
    rule_set = CelRuleSet(
        rules=[
            CelRule(
                expression="null",
                captures=[
                    CelRegexCapture(
                        attribute="description",
                        pattern="[bad",
                        flags=[],
                        label="Interac line",
                    ),
                ],
            ),
        ],
    )
    with pytest.raises(CelRuleSetValidationError) as exc_info:
        validate_cel_rule_set(rule_set)
    issue = exc_info.value.issues[0]
    assert issue.field == "pattern"
    assert issue.capture_index == 0
    assert issue.matcher_label == "Interac line"


def test_validate_unknown_regex_flag() -> None:
    rule_set = CelRuleSet(
        rules=[
            CelRule(
                expression="null",
                captures=[
                    CelRegexCapture(attribute="description", pattern=".*", flags=["bogus"]),
                ],
            ),
        ],
    )
    with pytest.raises(CelRuleSetValidationError) as exc_info:
        validate_cel_rule_set(rule_set)
    assert "unsupported regex flag" in exc_info.value.issues[0].message


def test_validate_valid_rule_set_passes() -> None:
    rule_set = CelRuleSet(
        rules=[
            CelRule(expression='{"set": {"tag": "ok"}}', captures=[]),
            CelRule(
                enabled=False,
                expression="null",
                captures=[
                    CelRegexCapture(attribute="description", pattern=r".*", flags=["ignorecase"]),
                ],
            ),
        ],
    )
    validate_cel_rule_set(rule_set)

