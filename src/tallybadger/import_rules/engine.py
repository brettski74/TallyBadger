from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from tallybadger.import_rules.errors import ImportRulesError
from tallybadger.import_rules.models import (
    Action,
    AppendToAttributeAction,
    ContainsMatcher,
    DayOfMonthMatcher,
    DayOfWeekMatcher,
    DropRowAction,
    EqualsMatcher,
    EvaluationResult,
    InSetMatcher,
    Matcher,
    NotEqualsMatcher,
    NumericCompareMatcher,
    RegexGroupRef,
    RegexMatcher,
    RequireReviewAction,
    Rule,
    RuleSet,
    SetAttributeAction,
    StopAction,
    TraceEvent,
)


def _rule_label(rule: Rule, index: int) -> str:
    if rule.id:
        return rule.id
    if rule.name:
        return rule.name
    return f"rule[{index}]"


def _compile_regex_flags(names: list[str]) -> int:
    flags = 0
    for n in names:
        if n == "ignorecase":
            flags |= re.IGNORECASE
        elif n == "multiline":
            flags |= re.MULTILINE
        elif n == "dotall":
            flags |= re.DOTALL
    return flags


def _try_match(
    matcher: Matcher,
    bag: dict[str, str],
) -> tuple[bool, re.Match[str] | None]:
    if isinstance(matcher, RegexMatcher):
        raw = bag.get(matcher.attribute)
        hay = "" if raw is None else str(raw)
        flags = _compile_regex_flags(list(matcher.flags))
        try:
            m = re.search(matcher.pattern, hay, flags)
        except re.error as exc:
            raise ImportRulesError(f"invalid regex pattern: {exc}") from exc
        return (m is not None, m)

    if isinstance(matcher, EqualsMatcher):
        raw = bag.get(matcher.attribute)
        left = "" if raw is None else str(raw)
        right = matcher.value
        if matcher.case_insensitive:
            ok = left.strip().casefold() == right.strip().casefold()
        else:
            ok = left == right
        return (ok, None)

    if isinstance(matcher, NotEqualsMatcher):
        raw = bag.get(matcher.attribute)
        left = "" if raw is None else str(raw)
        right = matcher.value
        if matcher.case_insensitive:
            ok = left.strip().casefold() != right.strip().casefold()
        else:
            ok = left != right
        return (ok, None)

    if isinstance(matcher, ContainsMatcher):
        raw = bag.get(matcher.attribute)
        hay = "" if raw is None else str(raw)
        needle = matcher.substring
        if matcher.case_insensitive:
            ok = needle.casefold() in hay.casefold()
        else:
            ok = needle in hay
        return (ok, None)

    if isinstance(matcher, NumericCompareMatcher):
        raw = bag.get(matcher.attribute)
        if raw is None or not str(raw).strip():
            return (False, None)
        try:
            left = Decimal(str(raw).strip())
            right = Decimal(str(matcher.value).strip())
        except (InvalidOperation, ValueError):
            return (False, None)
        op = matcher.op
        if op == "lt":
            ok = left < right
        elif op == "lte":
            ok = left <= right
        elif op == "eq":
            ok = left == right
        elif op == "gte":
            ok = left >= right
        else:
            ok = left > right
        return (ok, None)

    if isinstance(matcher, InSetMatcher):
        raw = bag.get(matcher.attribute)
        val = "" if raw is None else str(raw)
        ok = val in matcher.values
        return (ok, None)

    if isinstance(matcher, DayOfMonthMatcher):
        raw = bag.get(matcher.attribute)
        if raw is None or not str(raw).strip():
            return (False, None)
        try:
            d = date.fromisoformat(str(raw).strip())
        except ValueError:
            return (False, None)
        ok = d.day in matcher.days
        return (ok, None)

    if isinstance(matcher, DayOfWeekMatcher):
        raw = bag.get(matcher.attribute)
        if raw is None or not str(raw).strip():
            return (False, None)
        try:
            d = date.fromisoformat(str(raw).strip())
        except ValueError:
            return (False, None)
        ok = d.weekday() in matcher.weekdays
        return (ok, None)

    raise ImportRulesError(f"unknown matcher type: {type(matcher)!r}")


def _resolve_value_from_regex_group(
    refs: list[re.Match[str] | None],
    ref: RegexGroupRef,
) -> str:
    if ref.matcher_index >= len(refs):
        raise ImportRulesError(f"matcher_index {ref.matcher_index} out of range for this rule")
    m = refs[ref.matcher_index]
    if m is None:
        raise ImportRulesError(
            f"no regex match at matcher_index {ref.matcher_index} for from_regex_group",
        )
    try:
        if isinstance(ref.group, int):
            got = m.group(ref.group)
        else:
            got = m.group(ref.group)
    except IndexError as exc:
        raise ImportRulesError(f"regex group {ref.group!r} not present in match") from exc
    return "" if got is None else str(got)


def _resolve_fragment(
    bag: dict[str, str],
    refs: list[re.Match[str] | None],
    literal_value: str | None,
    from_attribute: str | None,
    from_regex_group: RegexGroupRef | None,
) -> str:
    if literal_value is not None:
        return literal_value
    if from_attribute is not None:
        raw = bag.get(from_attribute)
        return "" if raw is None else str(raw)
    if from_regex_group is not None:
        return _resolve_value_from_regex_group(refs, from_regex_group)
    raise ImportRulesError("internal: no value source for fragment")


def _apply_action(
    action: Action,
    bag: dict[str, str],
    regex_matches: list[re.Match[str] | None],
    trace: list[TraceEvent],
    rule_label: str,
) -> tuple[bool, bool]:
    """Returns (stop_rules, dropped)."""
    if isinstance(action, SetAttributeAction):
        val = _resolve_fragment(
            bag,
            regex_matches,
            action.literal_value,
            action.from_attribute,
            action.from_regex_group,
        )
        bag[action.name] = val
        trace.append(
            TraceEvent(
                event="set_attribute",
                detail={"rule": rule_label, "name": action.name, "value": val},
            ),
        )
        return (False, False)

    if isinstance(action, AppendToAttributeAction):
        frag = _resolve_fragment(
            bag,
            regex_matches,
            action.literal_value,
            action.from_attribute,
            action.from_regex_group,
        )
        cur = bag.get(action.name, "")
        if cur:
            bag[action.name] = cur + action.separator + frag
        else:
            bag[action.name] = frag
        trace.append(
            TraceEvent(
                event="append_to_attribute",
                detail={"rule": rule_label, "name": action.name, "fragment": frag},
            ),
        )
        return (False, False)

    if isinstance(action, StopAction):
        trace.append(TraceEvent(event="stop", detail={"rule": rule_label}))
        return (True, False)

    if isinstance(action, DropRowAction):
        trace.append(
            TraceEvent(
                event="drop_row",
                detail={"rule": rule_label, "reason": action.reason},
            ),
        )
        return (False, True)

    if isinstance(action, RequireReviewAction):
        trace.append(
            TraceEvent(
                event="require_review",
                detail={"rule": rule_label, "reason": action.reason},
            ),
        )
        return (False, False)

    raise ImportRulesError(f"unknown action type: {type(action)!r}")


def evaluate(rule_set: RuleSet, attributes: dict[str, Any]) -> EvaluationResult:
    """
    Run ordered rules against a copy of `attributes` (values coerced to str).

    Stops processing further rules after ``stop`` or ``drop_row``, or when a rule
    action requests stop. ``require_review`` sets flags but does not halt rules
    unless combined with ``stop`` / ``drop_row``.
    """
    bag: dict[str, str] = {k: "" if v is None else str(v) for k, v in attributes.items()}
    trace: list[TraceEvent] = []
    dropped = False
    drop_reason: str | None = None
    require_review = False
    review_reason: str | None = None
    stopped_after: str | None = None

    indexed = sorted(enumerate(rule_set.rules), key=lambda t: (t[1].sort_order, t[0]))
    for orig_idx, rule in indexed:
        label = _rule_label(rule, orig_idx)
        if dropped:
            break
        if not rule.enabled:
            trace.append(TraceEvent(event="rule_skipped", detail={"rule": label, "reason": "disabled"}))
            continue

        trace.append(TraceEvent(event="rule_tried", detail={"rule": label}))
        regex_matches: list[re.Match[str] | None] = [None] * len(rule.matchers)
        matched = True
        for i, m in enumerate(rule.matchers):
            ok, rx = _try_match(m, bag)
            if isinstance(m, RegexMatcher):
                regex_matches[i] = rx
            if not ok:
                matched = False
                break

        if not matched:
            trace.append(TraceEvent(event="rule_not_matched", detail={"rule": label}))
            continue

        trace.append(TraceEvent(event="rule_matched", detail={"rule": label}))

        stop_rules = False
        for action in rule.actions:
            if dropped:
                break
            stop_rules, row_dropped = _apply_action(action, bag, regex_matches, trace, label)
            if isinstance(action, RequireReviewAction):
                require_review = True
                if action.reason:
                    review_reason = action.reason
            if row_dropped:
                dropped = True
                drop_reason = action.reason if isinstance(action, DropRowAction) else None
                break
            if stop_rules:
                stopped_after = label
                break
        if stop_rules or dropped:
            break

    return EvaluationResult(
        attributes=bag,
        dropped=dropped,
        drop_reason=drop_reason,
        require_review=require_review,
        review_reason=review_reason,
        stopped_after_rule=stopped_after,
        trace=trace,
    )
