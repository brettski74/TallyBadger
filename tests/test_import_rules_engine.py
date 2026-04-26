"""Unit tests for the import rules engine (#8)."""

import pytest

from tallybadger.import_rules.engine import evaluate
from tallybadger.import_rules.errors import ImportRulesError
from tallybadger.import_rules.models import (
    AppendToAttributeAction,
    ContainsMatcher,
    DayOfMonthMatcher,
    DayOfWeekMatcher,
    DropRowAction,
    EqualsMatcher,
    InSetMatcher,
    NotEqualsMatcher,
    NumericCompareMatcher,
    RegexGroupRef,
    RegexMatcher,
    RequireReviewAction,
    Rule,
    RuleSet,
    SetAttributeAction,
    StopAction,
)


def test_vacuous_matchers_run_actions() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                id="r1",
                sort_order=10,
                matchers=[],
                actions=[SetAttributeAction(name="kind", literal_value="misc")],
            ),
        ],
    )
    out = evaluate(rs, {"description": "hello"})
    assert out.attributes["kind"] == "misc"
    assert not out.dropped


def test_rule_order_and_stop_skips_later_rules() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                id="first",
                sort_order=10,
                matchers=[EqualsMatcher(attribute="a", value="1")],
                actions=[SetAttributeAction(name="x", literal_value="from_first"), StopAction()],
            ),
            Rule(
                id="second",
                sort_order=20,
                matchers=[],
                actions=[SetAttributeAction(name="x", literal_value="from_second")],
            ),
        ],
    )
    out = evaluate(rs, {"a": "1"})
    assert out.attributes["x"] == "from_first"
    assert out.stopped_after_rule == "first"


def test_stop_only_when_rule_matches() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                id="no_match_stop",
                sort_order=10,
                matchers=[EqualsMatcher(attribute="a", value="nope")],
                actions=[StopAction()],
            ),
            Rule(
                id="runs",
                sort_order=20,
                matchers=[],
                actions=[SetAttributeAction(name="x", literal_value="ok")],
            ),
        ],
    )
    out = evaluate(rs, {"a": "1"})
    assert out.attributes["x"] == "ok"
    assert out.stopped_after_rule is None


def test_regex_named_group_sets_attribute_for_later_rule() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                id="parse_emt",
                sort_order=10,
                matchers=[
                    RegexMatcher(
                        attribute="description",
                        pattern=r"EMT\s*-\s*(?P<sender>[^,]+),",
                    ),
                ],
                actions=[
                    SetAttributeAction(
                        name="party_name_hint",
                        from_regex_group=RegexGroupRef(matcher_index=0, group="sender"),
                    ),
                ],
            ),
            Rule(
                id="tag",
                sort_order=20,
                matchers=[ContainsMatcher(attribute="party_name_hint", substring="ACME")],
                actions=[SetAttributeAction(name="vendor_tag", literal_value="acme")],
            ),
        ],
    )
    out = evaluate(rs, {"description": "EMT - ACME CORP, ref 99"})
    assert out.attributes["party_name_hint"].strip() == "ACME CORP"
    assert out.attributes["vendor_tag"] == "acme"


def test_regex_numbered_group() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                matchers=[
                    RegexMatcher(attribute="memo", pattern=r"^INV-(\d+)$"),
                ],
                actions=[
                    SetAttributeAction(
                        name="invoice_no",
                        from_regex_group=RegexGroupRef(matcher_index=0, group=1),
                    ),
                ],
            ),
        ],
    )
    out = evaluate(rs, {"memo": "INV-404"})
    assert out.attributes["invoice_no"] == "404"


def test_drop_row_stops_processing() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                id="junk",
                sort_order=10,
                matchers=[ContainsMatcher(attribute="description", substring="BALANCE FORWARD")],
                actions=[DropRowAction(reason="header row")],
            ),
            Rule(
                id="never",
                sort_order=20,
                matchers=[],
                actions=[SetAttributeAction(name="x", literal_value="nope")],
            ),
        ],
    )
    out = evaluate(rs, {"description": "BALANCE FORWARD"})
    assert out.dropped
    assert out.drop_reason == "header row"
    assert "x" not in out.attributes


def test_overwrite_by_later_rule() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                sort_order=10,
                matchers=[],
                actions=[SetAttributeAction(name="acct", literal_value="100")],
            ),
            Rule(
                sort_order=20,
                matchers=[],
                actions=[SetAttributeAction(name="acct", literal_value="200")],
            ),
        ],
    )
    out = evaluate(rs, {})
    assert out.attributes["acct"] == "200"


def test_append_to_attribute() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                matchers=[],
                actions=[
                    SetAttributeAction(name="memo", literal_value="a"),
                ],
            ),
            Rule(
                matchers=[],
                actions=[
                    AppendToAttributeAction(name="memo", literal_value="b", separator="|"),
                ],
            ),
        ],
    )
    out = evaluate(rs, {})
    assert out.attributes["memo"] == "a|b"


def test_numeric_compare() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                matchers=[NumericCompareMatcher(attribute="amount", op="gt", value="100")],
                actions=[SetAttributeAction(name="big", literal_value="true")],
            ),
        ],
    )
    assert evaluate(rs, {"amount": "150"}).attributes.get("big") == "true"
    assert evaluate(rs, {"amount": "50"}).attributes.get("big") is None


def test_in_set_and_not_equals() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                matchers=[
                    InSetMatcher(attribute="type", values=["debit", "credit"]),
                    NotEqualsMatcher(attribute="type", value="credit"),
                ],
                actions=[SetAttributeAction(name="flow", literal_value="out")],
            ),
        ],
    )
    out = evaluate(rs, {"type": "debit"})
    assert out.attributes["flow"] == "out"


def test_day_of_month_matcher() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                matchers=[DayOfMonthMatcher(attribute="posted_on", days=[1, 15])],
                actions=[SetAttributeAction(name="payroll_window", literal_value="yes")],
            ),
        ],
    )
    assert evaluate(rs, {"posted_on": "2026-04-15"}).attributes.get("payroll_window") == "yes"
    assert evaluate(rs, {"posted_on": "2026-04-16"}).attributes.get("payroll_window") is None


def test_day_of_week_matcher() -> None:
    # 2026-04-26 is Sunday -> weekday() == 6
    rs = RuleSet(
        rules=[
            Rule(
                matchers=[DayOfWeekMatcher(attribute="posted_on", weekdays=[6])],
                actions=[SetAttributeAction(name="weekend", literal_value="yes")],
            ),
        ],
    )
    out = evaluate(rs, {"posted_on": "2026-04-26"})
    assert out.attributes["weekend"] == "yes"


def test_require_review_flag() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                matchers=[],
                actions=[RequireReviewAction(reason="check party")],
            ),
            Rule(
                matchers=[],
                actions=[SetAttributeAction(name="x", literal_value="1")],
            ),
        ],
    )
    out = evaluate(rs, {})
    assert out.require_review
    assert out.review_reason == "check party"
    assert out.attributes["x"] == "1"


def test_bad_regex_group_ref_raises() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                matchers=[RegexMatcher(attribute="d", pattern=r"(a)")],
                actions=[
                    SetAttributeAction(
                        name="x",
                        from_regex_group=RegexGroupRef(matcher_index=0, group=99),
                    ),
                ],
            ),
        ],
    )
    with pytest.raises(ImportRulesError):
        evaluate(rs, {"d": "a"})


def test_trace_records_rule_flow() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                id="a",
                sort_order=10,
                matchers=[EqualsMatcher(attribute="k", value="v")],
                actions=[SetAttributeAction(name="n", literal_value="1")],
            ),
        ],
    )
    out = evaluate(rs, {"k": "v"})
    kinds = [t.event for t in out.trace]
    assert kinds == ["rule_tried", "rule_matched", "set_attribute"]


def test_disabled_rule_skipped() -> None:
    rs = RuleSet(
        rules=[
            Rule(
                id="off",
                enabled=False,
                matchers=[],
                actions=[SetAttributeAction(name="x", literal_value="bad")],
            ),
            Rule(
                id="on",
                sort_order=10,
                matchers=[],
                actions=[SetAttributeAction(name="x", literal_value="good")],
            ),
        ],
    )
    out = evaluate(rs, {})
    assert out.attributes["x"] == "good"
