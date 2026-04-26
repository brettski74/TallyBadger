from __future__ import annotations

from datetime import date

import pytest

from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import CelRegexCapture, CelRule, CelRuleSet
from tallybadger.import_rules.errors import ImportRulesCelError


def test_cel_rule_can_set_attributes_and_keep_types() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                id="r1",
                sort_order=10,
                expression='{"set":{"category":"rent","amount_copy": attributes["amount"]}}',
            ),
        ],
    )
    out = evaluate_cel(rs, {"amount": 1200, "memo": "x"})
    assert out.attributes["category"] == "rent"
    assert out.attributes["amount_copy"] == 1200
    assert out.attributes["amount"] == 1200


def test_cel_rule_returns_null_for_no_match() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='attributes["amount"] > 100 ? {"set":{"big":true}} : null',
            ),
        ],
    )
    assert evaluate_cel(rs, {"amount": 50}).attributes.get("big") is None
    assert evaluate_cel(rs, {"amount": 150}).attributes.get("big") is True


def test_stop_drop_review_are_nullable_reason_strings() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                id="a",
                sort_order=10,
                expression='{"set":{"x":1},"review":"needs eyeballs"}',
            ),
            CelRule(
                id="b",
                sort_order=20,
                expression='{"set":{"x":2},"stop":"done for row"}',
            ),
            CelRule(
                id="c",
                sort_order=30,
                expression='{"set":{"x":3}}',
            ),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.attributes["x"] == 2
    assert out.require_review is True
    assert out.review_reason == "needs eyeballs"
    assert out.stopped_after_rule == "b"


def test_drop_stops_and_sets_reason() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(expression='{"drop":"junk row"}'),
            CelRule(expression='{"set":{"x":1}}'),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.dropped is True
    assert out.drop_reason == "junk row"
    assert out.attributes.get("x") is None


def test_regex_captures_available_in_expression() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                captures=[
                    CelRegexCapture(
                        attribute="description",
                        pattern=r"EMT\s*-\s*(?P<sender>[^,]+),",
                    ),
                ],
                expression=(
                    'match[0]["ok"] ? {"set":{"party_name_hint": match[0]["groups"]["sender"],'
                    '"label": string(attributes["posted_on"]) + " " + match[0]["groups"]["sender"] + " Rent"}} : null'
                ),
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"description": "EMT - ACME, ref 1", "posted_on": date(2026, 4, 1)},
    )
    assert out.attributes["party_name_hint"] == "ACME"
    assert out.attributes["label"] == "2026-04-01 ACME Rent"


def test_non_map_result_treated_as_no_match_in_spike() -> None:
    rs = CelRuleSet(rules=[CelRule(expression="true")])
    out = evaluate_cel(rs, {})
    assert out.trace[-1].event == "rule_not_matched"


def test_invalid_stop_type_raises() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"stop":true}')])
    with pytest.raises(ImportRulesCelError, match="stop"):
        evaluate_cel(rs, {})
