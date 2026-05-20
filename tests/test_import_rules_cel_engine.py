from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import CelRegexCapture, CelRule, CelRuleSet
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.models import AccountOut, ChequeOut, PartyOut


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


def test_cel_default_account_name_seeded_before_rules() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                sort_order=10,
                expression='{"set":{"seen": attributes["default-account"]}}',
            ),
        ],
    )
    out = evaluate_cel(rs, {"marker": 1}, default_account_name="Chequing")
    assert out.attributes.get("seen") == "Chequing"
    assert out.attributes.get("default-account") == "Chequing"
    assert out.attributes.get("marker") == 1


def test_cel_default_account_name_skips_when_bag_has_key() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                sort_order=10,
                expression='{"set":{"seen": attributes["default-account"]}}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"default-account": "Override"},
        default_account_name="Chequing",
    )
    assert out.attributes.get("seen") == "Override"
    assert out.attributes.get("default-account") == "Override"


def test_cel_default_account_name_whitespace_only_does_not_seed() -> None:
    rs = CelRuleSet(rules=[CelRule(expression="null")])
    out = evaluate_cel(rs, {"k": 1}, default_account_name="   \t")
    assert "default-account" not in out.attributes


def test_cel_unset_removes_key_from_attribute_bag() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"tag": unset()}}')])
    out = evaluate_cel(rs, {"tag": "x", "keep": 1})
    assert "tag" not in out.attributes
    assert out.attributes["keep"] == 1
    removed = [t for t in out.trace if t.event == "remove_attribute"]
    assert len(removed) == 1
    assert removed[0].detail == {"rule": "rule[0]", "name": "tag"}


def test_cel_unset_on_missing_key_is_noop() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"only_in_rule": unset()}}')])
    out = evaluate_cel(rs, {"keep": 2})
    assert "only_in_rule" not in out.attributes
    assert out.attributes["keep"] == 2


def test_cel_later_rule_unset_after_earlier_set() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(sort_order=1, expression='{"set":{"flag": true}}'),
            CelRule(sort_order=2, expression='{"set":{"flag": unset()}}'),
        ],
    )
    out = evaluate_cel(rs, {})
    assert "flag" not in out.attributes


def test_cel_set_null_still_leaves_key_with_none() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"x": null}}')])
    out = evaluate_cel(rs, {})
    assert "x" in out.attributes
    assert out.attributes["x"] is None
    set_ev = [t for t in out.trace if t.event == "set_attribute"]
    assert any(t.detail.get("name") == "x" and t.detail.get("value") is None for t in set_ev)


def test_cel_debug_serializes_unset_marker() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"z": debug(unset())}}')])
    out = evaluate_cel(rs, {"k": 1})
    assert out.debug is not None
    assert out.debug[0].value == "<unset>"
    assert "z" not in out.attributes


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
    assert out.review_messages == ["needs eyeballs"]
    assert out.stopped_after_rule == "b"


def test_review_messages_accumulate_across_rules() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(sort_order=10, expression='{"review":"first"}'),
            CelRule(sort_order=20, expression='{"review":"second"}'),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.review_messages == ["first", "second"]


def test_review_in_set_map_does_not_enter_attribute_bag() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(expression='{"set":{"review":"side channel","x":1}}'),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.review_messages == ["side channel"]
    assert out.attributes.get("x") == 1
    assert "review" not in out.attributes


def test_empty_top_level_review_string_rejected() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"review":""}')])
    with pytest.raises(ImportRulesCelError, match="non-empty"):
        evaluate_cel(rs, {})


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


def _account_row(**kwargs: object) -> AccountOut:
    base: dict[str, object] = {
        "id": 1,
        "name": "Operating",
        "type": "asset",
        "is_active": True,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    base.update(kwargs)
    return AccountOut.model_validate(base)


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


def _cheque_row(**kwargs: object) -> ChequeOut:
    base: dict[str, object] = {
        "id": 1,
        "credit_account_id": 10,
        "debit_account_id": 20,
        "summary": "May rent",
        "cheque_number": 42,
        "issue_date": date(2026, 5, 1),
        "cleared_date": None,
        "amount": Decimal("100.00"),
        "party_id": None,
        "status": "open",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    base.update(kwargs)
    return ChequeOut.model_validate(base)


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


def test_cel_account_helpers_null_without_role_or_default_issue_61() -> None:
    """expense_account / revenue_account / equity_account do not error on 'wrong' role; null if unset."""
    customer = _party_row(
        id=10,
        name="RetailCo",
        role="customer",
        match_patterns=[],
        default_revenue_account_name="Sales",
        default_expense_account_name=None,
    )
    vendor = _party_row(
        id=11,
        name="SupplyCo",
        role="vendor",
        match_patterns=[],
        default_revenue_account_name=None,
        default_expense_account_name="Job Supplies",
    )
    bare_customer = _party_row(
        id=12,
        name="WalkIn",
        role="customer",
        match_patterns=[],
        default_revenue_account_name=None,
    )
    both_party = _party_row(
        id=13,
        name="BothCo",
        role="both",
        match_patterns=[],
        default_revenue_account_name="Mixed Rev",
        default_expense_account_name="Mixed Exp",
    )
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{'
                    '"c_exp": expense_account("RetailCo"), '
                    '"c_rev": revenue_account("RetailCo"), '
                    '"v_rev": revenue_account("SupplyCo"), '
                    '"v_eq": equity_account("SupplyCo"), '
                    '"v_exp": expense_account("SupplyCo"), '
                    '"bare_rev": revenue_account("WalkIn"), '
                    '"b_rev": revenue_account("BothCo"), '
                    '"b_exp": expense_account("BothCo") '
                    "}}"
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {}, parties=[customer, vendor, bare_customer, both_party])
    assert out.attributes["c_exp"] is None
    assert out.attributes["c_rev"] == "Sales"
    assert out.attributes["v_rev"] is None
    assert out.attributes["v_eq"] is None
    assert out.attributes["v_exp"] == "Job Supplies"
    assert out.attributes["bare_rev"] is None
    assert out.attributes["b_rev"] == "Mixed Rev"
    assert out.attributes["b_exp"] == "Mixed Exp"


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


def test_debug_identity_does_not_change_rule_outcome() -> None:
    baseline = evaluate_cel(
        CelRuleSet(rules=[CelRule(expression='{"set":{"x": 1 + 2}}')]),
        {},
    )
    with_debug = evaluate_cel(
        CelRuleSet(rules=[CelRule(expression='{"set":{"x": debug(1 + 2)}}')]),
        {},
    )
    assert baseline.attributes == with_debug.attributes
    assert with_debug.debug is not None
    assert len(with_debug.debug) == 1
    assert with_debug.debug[0].value == 3


def test_debug_order_and_multiplicity() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set":{"seq": [debug(1), debug(2)]}}',
            ),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.attributes["seq"] == [1, 2]
    assert out.debug is not None
    assert [e.value for e in out.debug] == [1, 2]


def test_debug_rule_label_named_vs_unnamed() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(name="named", expression='{"set":{"a": debug("x")}}'),
            CelRule(expression='{"set":{"b": debug("y")}}'),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.debug is not None
    assert len(out.debug) == 2
    assert out.debug[0].rule == "named"
    assert out.debug[0].value == "x"
    assert out.debug[0].row_number is None
    assert out.debug[1].rule == "rule[1]"
    assert out.debug[1].value == "y"


def test_debug_row_number_evaluate_param() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"z": debug(attributes["k"])}}')])
    out = evaluate_cel(rs, {"k": 42}, row_number=7)
    assert out.debug is not None
    assert len(out.debug) == 1
    assert out.debug[0].row_number == 7
    assert out.debug[0].value == 42


def test_debug_row_number_omitted_when_not_passed() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"z": debug(1)}}')])
    out = evaluate_cel(rs, {})
    assert out.debug is not None
    assert out.debug[0].row_number is None


def test_debug_not_run_when_capture_fails() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                captures=[CelRegexCapture(attribute="d", pattern=r"^NO$")],
                expression='{"set":{"ran": debug(true)}}',
            ),
        ],
    )
    out = evaluate_cel(rs, {"d": "yes"})
    assert out.debug is None


def test_debug_two_rules_same_row_distinct_rule_field() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(name="first", sort_order=1, expression='{"set":{"x": debug(1)}}'),
            CelRule(name="second", sort_order=2, expression='{"set":{"y": debug(2)}}'),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.debug is not None
    assert [(e.rule, e.value) for e in out.debug] == [("first", 1), ("second", 2)]


def test_cel_abs_int_double_and_numeric_string() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{"a": abs(-3), "b": abs(-2.5), "c": abs(attributes["s"]), '
                    '"d": abs(attributes["dec"])}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {"s": "-4", "dec": Decimal("-1.25")})
    assert out.attributes["a"] == 3
    assert out.attributes["b"] == 2.5
    assert out.attributes["c"] == 4
    assert out.attributes["d"] == 1.25


def test_cel_abs_non_numeric_errors() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"x": abs(attributes["s"])}}')])
    with pytest.raises(ImportRulesCelError, match="abs"):
        evaluate_cel(rs, {"s": "nope"})


def test_cel_day_and_month_from_iso_strings() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{"dom": day(attributes["d"]), "mon": month(attributes["d"]), '
                    '"dt": day(attributes["ts"]), "tm": month(attributes["ts"])}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {"d": "2026-04-10", "ts": "2026-04-10T15:00:00Z"})
    assert out.attributes["dom"] == 10
    assert out.attributes["mon"] == 4
    assert out.attributes["dt"] == 10
    assert out.attributes["tm"] == 4


def test_cel_decode_map_lookup() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{"a": decode(attributes["k"], {"rent": "R", "fee": "F"}, "Z"), '
                    '"b": decode("nosuchkey", {"x": 1}, "none")}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {"k": "rent"})
    assert out.attributes["a"] == "R"
    assert out.attributes["b"] == "none"


def test_cel_decode_null_lookup_returns_default() -> None:
    rs = CelRuleSet(
        rules=[CelRule(expression='{"set":{"x": decode(null, {"a": 1}, "fallback")}}')],
    )
    out = evaluate_cel(rs, {})
    assert out.attributes["x"] == "fallback"


def test_cel_defined_respects_bag_updates_across_rules() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(sort_order=1, expression='{"set":{"mid": "v"}}'),
            CelRule(
                sort_order=2,
                expression='defined("mid") && !defined("absent") ? {"set":{"ok": true}} : null',
            ),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.attributes["ok"] is True


def test_cel_defined_false_for_empty_null_missing() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{"m": defined("missing"), "e": defined("empty"), '
                    '"n": defined("nullv"), "b": defined("blank_key")}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {"empty": "", "nullv": None, "blank_key": "  \t"})
    assert out.attributes["m"] is False
    assert out.attributes["e"] is False
    assert out.attributes["n"] is False
    assert out.attributes["b"] is True


def test_cel_account_type_active() -> None:
    cash = _account_row(id=1, name="  Petty  ", type="asset")
    rs = CelRuleSet(
        rules=[CelRule(expression='{"set":{"t": account_type("Petty")}}')],
    )
    out = evaluate_cel(rs, {}, accounts=[cash])
    assert out.attributes["t"] == "asset"


def test_cel_account_type_unknown_errors() -> None:
    cash = _account_row(id=2, name="Old", type="expense", is_active=True)
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"x": account_type("Nope")}}')])
    with pytest.raises(ImportRulesCelError, match="unknown"):
        evaluate_cel(rs, {}, accounts=[cash])


def test_cel_account_type_inactive_errors() -> None:
    cash = _account_row(id=2, name="Old", type="expense", is_active=False)
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"x": account_type("Old")}}')])
    with pytest.raises(ImportRulesCelError, match="inactive"):
        evaluate_cel(rs, {}, accounts=[cash])


def test_cel_account_type_blank_errors() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"x": account_type("  ")}}')])
    with pytest.raises(ImportRulesCelError, match="blank"):
        evaluate_cel(rs, {}, accounts=[])


def test_cel_match_date_issue_examples() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set":{"a": match_date(attributes["d"], 8, 2), "b": match_date(attributes["d"], 8, 1)}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {"d": "2026-04-10"})
    assert out.attributes["a"] is True
    assert out.attributes["b"] is False


def test_cel_match_date_invalid_params() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"x": match_date(attributes["d"], 0, 1)}}')])
    with pytest.raises(ImportRulesCelError, match="match_date day"):
        evaluate_cel(rs, {"d": "2026-04-10"})
    rs2 = CelRuleSet(rules=[CelRule(expression='{"set":{"x": match_date(attributes["d"], 5, -1)}}')])
    with pytest.raises(ImportRulesCelError, match="tolerance"):
        evaluate_cel(rs2, {"d": "2026-04-10"})


def test_cel_merge_empty_list() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set": merge([])}')])
    out = evaluate_cel(rs, {})
    assert out.attributes == {}


def test_cel_merge_single_map() -> None:
    rs = CelRuleSet(
        rules=[CelRule(expression='{"set": merge([{"a": 1, "b": "x"}])}')],
    )
    out = evaluate_cel(rs, {})
    assert out.attributes == {"a": 1, "b": "x"}


def test_cel_merge_later_map_wins_on_clash() -> None:
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression=(
                    '{"set": merge([{"summary": "old", "amount": 1}, '
                    '{"summary": "new", "settlement": "receipt"}])}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {})
    assert out.attributes["summary"] == "new"
    assert out.attributes["amount"] == 1
    assert out.attributes["settlement"] == "receipt"


def test_cel_merge_non_map_element_errors() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set": merge([{"a": 1}, 2])}')])
    with pytest.raises(ImportRulesCelError, match="merge.*index 1"):
        evaluate_cel(rs, {})


def test_cel_nvl_first_non_null_wins() -> None:
    rs = CelRuleSet(
        rules=[CelRule(expression='{"set":{"party": nvl([attr["payee"], "Pamela Person"])}}')],
    )
    out = evaluate_cel(rs, {"payee": "Bob"})
    assert out.attributes["party"] == "Bob"


def test_cel_nvl_skips_nulls() -> None:
    rs = CelRuleSet(
        rules=[CelRule(expression='{"set":{"party": nvl([null, attr["payee"], "Pamela Person"])}}')],
    )
    out = evaluate_cel(rs, {"payee": "Bob"})
    assert out.attributes["party"] == "Bob"
    out2 = evaluate_cel(rs, {"payee": None})
    assert out2.attributes["party"] == "Pamela Person"


def test_cel_nvl_all_null_or_empty() -> None:
    rs = CelRuleSet(rules=[CelRule(expression='{"set":{"x": nvl([null, null])}}')])
    out = evaluate_cel(rs, {})
    assert out.attributes["x"] is None
    rs2 = CelRuleSet(rules=[CelRule(expression='{"set":{"x": nvl([])}}')])
    out2 = evaluate_cel(rs2, {})
    assert out2.attributes["x"] is None


def test_cel_cheque_match_sets_bag_and_omits_empty_review_messages() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(id=99, credit_account_id=10, debit_account_id=20, cheque_number=42)
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("100.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        cheques=[ch],
    )
    assert out.attributes["cheque-id"] == 99
    assert out.attributes["dr-account"] == "Rent Expense"
    assert out.attributes["summary"] == "May rent"
    assert out.attributes["cheque-amount"] == 100.0
    assert "review-messages" not in out.attributes
    assert out.review_messages == []


def test_cel_cheque_amount_is_numeric_for_later_rules() -> None:
    """cheque-amount must be a number so + is arithmetic, not string concat."""
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(credit_account_id=10, debit_account_id=20, amount=Decimal("100.00"))
    rs = CelRuleSet(
        rules=[
            CelRule(
                sort_order=10,
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
            CelRule(
                sort_order=20,
                expression='{"set": {"check_plus_one": attr["cheque-amount"] + 1}}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("100.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        cheques=[ch],
    )
    assert out.attributes["check_plus_one"] == 101.0


def test_cel_cheque_coerces_nr_from_numeric_string() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(credit_account_id=10, debit_account_id=20, cheque_number=42)
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", attr["nr"], attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"nr": "42", "amt": Decimal("100.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        cheques=[ch],
    )
    assert out.attributes["cheque-id"] == 1
    assert out.attributes["cheque-amount"] == 100.0


def test_cel_cheque_accepts_entry_date_as_iso_string() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(credit_account_id=10, debit_account_id=20)
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": "100.00", "entry_date": "2026-05-05"},
        accounts=[cr, dr],
        cheques=[ch],
    )
    assert out.attributes["cheque-id"] == 1
    assert out.review_messages == []


def test_cel_cheque_amount_mismatch_adds_review_message() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(credit_account_id=10, debit_account_id=20, amount=Decimal("100.00"))
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("99.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        cheques=[ch],
    )
    assert out.attributes["cheque-id"] == 1
    assert len(out.review_messages) == 1
    assert "$99.00" in out.review_messages[0] and "$100.00" in out.review_messages[0]


def test_cel_cheque_amount_mismatch_message_uses_thousands_separators() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(credit_account_id=10, debit_account_id=20, amount=Decimal("1234567.89"))
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("1.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        cheques=[ch],
    )
    msg = out.review_messages[0]
    assert "$1.00" in msg
    assert "$1,234,567.89" in msg


def test_cel_cheque_negative_import_amount_matches_positive_register() -> None:
    """Bank CSV often credits chequing with a negative amount; register stores face value."""
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(credit_account_id=10, debit_account_id=20, amount=Decimal("904.00"))
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("-904.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        cheques=[ch],
    )
    assert out.attributes["cheque-id"] == 1
    assert out.review_messages == []
    assert "review-messages" not in out.attributes


def test_cel_cheque_entry_date_before_issue_date_adds_review_message() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(
        credit_account_id=10,
        debit_account_id=20,
        issue_date=date(2026, 5, 10),
    )
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("100.00"), "entry_date": date(2026, 5, 1)},
        accounts=[cr, dr],
        cheques=[ch],
    )
    assert len(out.review_messages) == 1
    assert "2026-05-01" in out.review_messages[0]
    assert "2026-05-10" in out.review_messages[0]


def test_cel_cheque_no_open_match_no_cheque_id_in_bag() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("100.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        cheques=[],
    )
    assert "cheque-id" not in out.attributes
    assert "dr-account" not in out.attributes
    assert "summary" not in out.attributes
    assert "cheque-amount" not in out.attributes
    assert len(out.review_messages) >= 1


def test_cel_cheque_includes_dr_party_only_when_party_on_register_row() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    vendor = _party_row(id=5, name="Vendor Co", match_patterns=[])
    ch = _cheque_row(credit_account_id=10, debit_account_id=20, party_id=5)
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("100.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        parties=[vendor],
        cheques=[ch],
    )
    assert out.attributes["dr-party"] == "Vendor Co"


def test_cel_cheque_omits_dr_party_when_party_id_unknown_in_snapshot() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    ch = _cheque_row(credit_account_id=10, debit_account_id=20, party_id=999)
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("100.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        parties=[],
        cheques=[ch],
    )
    assert "dr-party" not in out.attributes


def test_cel_cheque_skips_non_open_rows() -> None:
    cr = _account_row(id=10, name="Operating", type="asset")
    dr = _account_row(id=20, name="Rent Expense", type="expense")
    voided = _cheque_row(credit_account_id=10, debit_account_id=20, status="void")
    rs = CelRuleSet(
        rules=[
            CelRule(
                expression='{"set": cheque("Operating", 42, attr["amt"], attr["entry_date"])}',
            ),
        ],
    )
    out = evaluate_cel(
        rs,
        {"amt": Decimal("100.00"), "entry_date": date(2026, 5, 5)},
        accounts=[cr, dr],
        cheques=[voided],
    )
    assert "cheque-id" not in out.attributes
    assert out.review_messages
