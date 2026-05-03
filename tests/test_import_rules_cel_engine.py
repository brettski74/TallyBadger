from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import CelRegexCapture, CelRule, CelRuleSet
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.models import PartyOut


def test_cel_rule_can_set_attributes_and_keep_types() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
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
                name="a",
                sort_order=10,
                expression='{"set":{"x":1},"review":"needs eyeballs"}',
            ),
            CelRule(
                name="b",
                sort_order=20,
                expression='{"set":{"x":2},"stop":"done for row"}',
            ),
            CelRule(
                name="c",
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


def test_capture_failure_skips_cel_expression() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                captures=[
                    CelRegexCapture(
                        attribute="description",
                        pattern=r"WILL_NOT_MATCH",
                    ),
                ],
                expression='{"set":{"expression_ran": true}}',
            ),
        ],
    )
    out = evaluate_cel(rs, {"description": "plain text"})
    assert out.attributes.get("expression_ran") is None
    failed = next(
        t for t in out.trace if t.event == "rule_not_matched" and t.detail.get("reason") == "capture_failed"
    )
    assert failed.detail.get("matcher_label") == "description"


def test_capture_failure_trace_uses_matcher_label_when_set() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                captures=[
                    CelRegexCapture(
                        attribute="description",
                        pattern=r"WILL_NOT_MATCH",
                        label="Bank memo pattern",
                    ),
                ],
                expression='{"set":{"expression_ran": true}}',
            ),
        ],
    )
    out = evaluate_cel(rs, {"description": "plain text"})
    failed = next(
        t for t in out.trace if t.event == "rule_not_matched" and t.detail.get("reason") == "capture_failed"
    )
    assert failed.detail.get("matcher_label") == "Bank memo pattern"


def test_second_capture_failure_skips_expression_short_circuits() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                captures=[
                    CelRegexCapture(attribute="a", pattern=r"^ok$"),
                    CelRegexCapture(attribute="b", pattern=r"^NO$"),
                ],
                expression='{"set":{"ran": true}}',
            ),
        ],
    )
    out = evaluate_cel(rs, {"a": "ok", "b": "nope"})
    assert out.attributes.get("ran") is None
    failed = [
        t.detail
        for t in out.trace
        if t.event == "rule_not_matched" and t.detail.get("reason") == "capture_failed"
    ]
    assert any(d.get("capture_index") == 1 for d in failed)


def test_two_captures_both_must_succeed_before_expression() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                captures=[
                    CelRegexCapture(attribute="x", pattern=r"1"),
                    CelRegexCapture(attribute="y", pattern=r"2"),
                ],
                expression=(
                    '{"set":{"combined": match[0]["whole"] + "-" + match[1]["whole"]}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {"x": "a1b", "y": "c2d"})
    assert out.attributes["combined"] == "1-2"


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
                    '{"set":{"party_name_hint": match[0]["groups"]["sender"],'
                    '"label": string(attributes["posted_on"]) + " " + match[0]["groups"]["sender"] + " Rent"}}'
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


def test_non_map_result_is_error() -> None:
    rs = CelRuleSet(rules=[CelRule(expression="true")])
    with pytest.raises(ImportRulesCelError, match="expected map/object or null"):
        evaluate_cel(rs, {})


def test_invalid_stop_type_raises() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"stop":true}')])
    with pytest.raises(ImportRulesCelError, match="stop"):
        evaluate_cel(rs, {})


def _party_row(**kwargs: object) -> PartyOut:
    base: dict[str, object] = {
        "id": 1,
        "name": "Alice",
        "role": "customer",
        "is_active": True,
        "match_patterns": [r"A\d+"],
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    base.update(kwargs)
    return PartyOut.model_validate(base)


def test_cel_party_resolves_with_patterns() -> None:
    p = _party_row(id=1, name="Alice", match_patterns=[r"A\d+"])
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"who": party(attributes["d"])}}')])
    out = evaluate_cel(rs, {"d": "X A99 Z"}, parties=[p])
    assert out.attributes["who"] == "Alice"


def test_cel_party_type_and_subtype() -> None:
    p = _party_row(id=2, name="Bob", role="vendor", subtype="gardener", match_patterns=[])
    rs = CelRuleSet(
        rules=[
            CelRule(expression='{"set":{"t": party_type("Bob"), "s": party_subtype("Bob")}}'),
        ],
    )
    out = evaluate_cel(rs, {}, parties=[p])
    assert out.attributes["t"] == "vendor"
    assert out.attributes["s"] == "gardener"


def test_cel_revenue_and_expense_account_names() -> None:
    rent = _party_row(
        id=3,
        name="Tenant",
        role="customer",
        match_patterns=[],
        default_revenue_account_name="Rent Revenue",
    )
    vend = _party_row(
        id=4,
        name="Plumber",
        role="vendor",
        match_patterns=[],
        default_expense_account_name="Repairs Expense",
    )
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{"r": revenue_account("Tenant"), "e": expense_account("Plumber")}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {}, parties=[rent, vend])
    assert out.attributes["r"] == "Rent Revenue"
    assert out.attributes["e"] == "Repairs Expense"


def test_equity_account_alias_matches_revenue_account() -> None:
    p = _party_row(
        id=5,
        name="Owner Party",
        role="customer",
        match_patterns=[],
        default_revenue_account_name="Owner Capital",
    )
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{"r": revenue_account("Owner Party"), "q": equity_account("Owner Party")}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {}, parties=[p])
    assert out.attributes["r"] == "Owner Capital"
    assert out.attributes["q"] == "Owner Capital"


def test_cel_party_type_subtype_and_accounts_blank_arg_returns_null() -> None:
    """Blank / whitespace-only party name args behave like a non-match (null), not an error."""
    p = _party_row(
        id=9,
        name="Zed",
        role="vendor",
        subtype=None,
        match_patterns=[],
        default_expense_account_name="Tools",
    )
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{'
                    '"pt": party_type(""), '
                    '"ps": party_subtype("  \\t"), '
                    '"ps2": party_subtype("Zed"), '
                    '"rv": revenue_account(""), '
                    '"eq": equity_account("   "), '
                    '"ex": expense_account("") '
                    "}}"
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {}, parties=[p])
    assert out.attributes["pt"] is None
    assert out.attributes["ps"] is None
    assert out.attributes["ps2"] == ""
    assert out.attributes["rv"] is None
    assert out.attributes["eq"] is None
    assert out.attributes["ex"] is None
