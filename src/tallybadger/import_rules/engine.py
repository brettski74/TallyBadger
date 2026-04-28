from __future__ import annotations

import re
from copy import copy
from datetime import date, datetime
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


def _as_decimal(raw: Any) -> Decimal | None:
    """Parse a numeric attribute for comparisons; bool is not treated as a number."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        return Decimal(str(raw))
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return Decimal(s)
        except (InvalidOperation, ValueError):
            return None
    return None


def _as_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            return None
    return None


def _scalar_equals(raw: Any, expected: str, case_insensitive: bool) -> bool:
    """Match rule string `expected` to a possibly typed attribute (decimal, date, str, …)."""
    if raw is None:
        return expected.strip() == ""
    exp = expected.strip()
    if case_insensitive and isinstance(raw, str):
        return raw.strip().casefold() == exp.casefold()
    left_d = _as_decimal(raw)
    right_d = _as_decimal(exp)
    if left_d is not None and right_d is not None:
        return left_d == right_d
    left_dt = _as_date(raw)
    if left_dt is not None:
        right_dt = _as_date(exp)
        if right_dt is not None:
            return left_dt == right_dt
    if case_insensitive:
        return str(raw).strip().casefold() == exp.casefold()
    return str(raw) == expected


def _display_for_concat(raw: Any) -> str:
    """Build a string fragment for append_to_attribute (dates as ISO date, decimals plain, etc.)."""
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    if isinstance(raw, Decimal):
        return format(raw, "f")
    if isinstance(raw, float):
        return str(raw)
    if isinstance(raw, int):
        return str(raw)
    return str(raw)


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
    bag: dict[str, Any],
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
        ok = _scalar_equals(raw, matcher.value, matcher.case_insensitive)
        return (ok, None)

    if isinstance(matcher, NotEqualsMatcher):
        raw = bag.get(matcher.attribute)
        ok = not _scalar_equals(raw, matcher.value, matcher.case_insensitive)
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
        left = _as_decimal(raw)
        try:
            right = Decimal(str(matcher.value).strip())
        except (InvalidOperation, ValueError):
            return (False, None)
        if left is None:
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
        ok = any(_scalar_equals(raw, v, False) for v in matcher.values)
        return (ok, None)

    if isinstance(matcher, DayOfMonthMatcher):
        raw = bag.get(matcher.attribute)
        d = _as_date(raw)
        if d is None:
            return (False, None)
        ok = d.day in matcher.days
        return (ok, None)

    if isinstance(matcher, DayOfWeekMatcher):
        raw = bag.get(matcher.attribute)
        d = _as_date(raw)
        if d is None:
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


def _resolve_append_fragment(
    bag: dict[str, Any],
    refs: list[re.Match[str] | None],
    literal_value: Any | None,
    from_attribute: str | None,
    from_regex_group: RegexGroupRef | None,
) -> str:
    if literal_value is not None:
        return _display_for_concat(literal_value)
    if from_attribute is not None:
        return _display_for_concat(bag.get(from_attribute))
    if from_regex_group is not None:
        return _resolve_value_from_regex_group(refs, from_regex_group)
    raise ImportRulesError("internal: no value source for fragment")


def _resolve_set_value(
    action: SetAttributeAction,
    bag: dict[str, Any],
    refs: list[re.Match[str] | None],
) -> Any:
    if action.literal_value is not None:
        v = action.literal_value
        return copy(v) if isinstance(v, (list, dict)) else v
    if action.from_attribute is not None:
        v = bag.get(action.from_attribute)
        return copy(v) if isinstance(v, (list, dict)) else v
    if action.from_regex_group is not None:
        return _resolve_value_from_regex_group(refs, action.from_regex_group)
    raise ImportRulesError("internal: no value source for set_attribute")


def _apply_action(
    action: Action,
    bag: dict[str, Any],
    regex_matches: list[re.Match[str] | None],
    trace: list[TraceEvent],
    rule_label: str,
) -> tuple[bool, bool]:
    """Returns (stop_rules, dropped)."""
    if isinstance(action, SetAttributeAction):
        val = _resolve_set_value(action, bag, regex_matches)
        bag[action.name] = val
        trace.append(
            TraceEvent(
                event="set_attribute",
                detail={"rule": rule_label, "name": action.name, "value": val},
            ),
        )
        return (False, False)

    if isinstance(action, AppendToAttributeAction):
        frag = _resolve_append_fragment(
            bag,
            regex_matches,
            action.literal_value,
            action.from_attribute,
            action.from_regex_group,
        )
        cur = bag.get(action.name)
        if cur is None or cur == "":
            bag[action.name] = frag
        else:
            bag[action.name] = _display_for_concat(cur) + action.separator + frag
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
    Run ordered rules against a shallow copy of ``attributes``.

    Values keep their types (numbers, strings, ISO dates as ``date`` if the caller
    passes them—JSON via the API typically yields int/float/str/bool/null).

    ``stop``, ``drop_row``, and ``require_review`` are ordinary actions from the
    author's perspective; only ``stop`` / ``drop_row`` halt further rules.
    ``require_review`` sets result flags only and does **not** stop processing.

    Stops processing further rules after ``stop`` or ``drop_row``.
    """
    bag: dict[str, Any] = {k: copy(v) if isinstance(v, (list, dict)) else v for k, v in attributes.items()}
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
