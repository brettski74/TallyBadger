from __future__ import annotations

import re
from copy import copy
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from celpy import Environment, celtypes

from tallybadger.import_rules.cel_models import (
    CelEvaluationResult,
    CelRegexCapture,
    CelRule,
    CelRuleSet,
    CelTraceEvent,
)
from tallybadger.import_rules.errors import ImportRulesCelError


def _compile_regex_flags(names: list[str]) -> int:
    flags = 0
    for n in names:
        if n == "ignorecase":
            flags |= re.IGNORECASE
        elif n == "multiline":
            flags |= re.MULTILINE
        elif n == "dotall":
            flags |= re.DOTALL
        else:
            raise ImportRulesCelError(f"unsupported regex flag: {n}")
    return flags


def _rule_label(rule: CelRule, index: int) -> str:
    if rule.name:
        return rule.name
    return f"rule[{index}]"


def _matcher_label(cap: CelRegexCapture) -> str:
    if cap.label:
        return cap.label
    return cap.attribute


def _to_cel_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return celtypes.BoolType(value)
    if isinstance(value, int):
        return celtypes.IntType(value)
    if isinstance(value, float):
        return celtypes.DoubleType(value)
    if isinstance(value, Decimal):
        return celtypes.DoubleType(float(value))
    if isinstance(value, datetime):
        return celtypes.StringType(value.isoformat())
    if isinstance(value, date):
        return celtypes.StringType(value.isoformat())
    if isinstance(value, str):
        return celtypes.StringType(value)
    if isinstance(value, list):
        return celtypes.ListType([_to_cel_value(v) for v in value])
    if isinstance(value, dict):
        return celtypes.MapType({celtypes.StringType(str(k)): _to_cel_value(v) for k, v in value.items()})
    return celtypes.StringType(str(value))


def _from_cel_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, celtypes.BoolType):
        return bool(value)
    if isinstance(value, celtypes.IntType):
        return int(value)
    if isinstance(value, celtypes.DoubleType):
        return float(value)
    if isinstance(value, celtypes.StringType):
        return str(value)
    if isinstance(value, celtypes.ListType):
        return [_from_cel_value(v) for v in list(value)]
    if isinstance(value, celtypes.MapType):
        out: dict[str, Any] = {}
        for k, v in dict(value).items():
            out[str(_from_cel_value(k))] = _from_cel_value(v)
        return out
    if isinstance(value, dict):
        return {str(k): _from_cel_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_cel_value(v) for v in value]
    return value


def _capture_entry(cap: CelRegexCapture, bag: dict[str, Any]) -> dict[str, Any]:
    raw = bag.get(cap.attribute)
    hay = "" if raw is None else str(raw)
    flags = _compile_regex_flags(cap.flags)
    try:
        m = re.search(cap.pattern, hay, flags)
    except re.error as exc:
        raise ImportRulesCelError(f"invalid capture regex: {exc}") from exc
    if m is None:
        return {"ok": False, "whole": None, "list": [], "groups": {}}
    groups = {k: v for k, v in m.groupdict().items() if v is not None}
    # 1-based capture list (`list[0]` is whole match)
    lst = [m.group(0), *list(m.groups())]
    return {"ok": True, "whole": m.group(0), "list": lst, "groups": groups}


def _normalize_rule_output(result: Any, rule_label: str) -> dict[str, Any] | None:
    py = _from_cel_value(result)
    if py is None:
        return None
    if not isinstance(py, dict):
        raise ImportRulesCelError(
            f"CEL rule {rule_label} returned {type(py).__name__}; expected map/object or null",
        )
    return py


def evaluate_cel(rule_set: CelRuleSet, attributes: dict[str, Any]) -> CelEvaluationResult:
    bag: dict[str, Any] = {k: copy(v) if isinstance(v, (list, dict)) else v for k, v in attributes.items()}
    trace: list[CelTraceEvent] = []
    dropped = False
    drop_reason: str | None = None
    require_review = False
    review_reason: str | None = None
    stopped_after_rule: str | None = None

    env = Environment()
    ordered = sorted(enumerate(rule_set.rules), key=lambda x: (x[1].sort_order, x[0]))
    for idx, rule in ordered:
        if dropped:
            break
        label = _rule_label(rule, idx)
        if not rule.enabled:
            trace.append(CelTraceEvent(event="rule_skipped", detail={"rule": label, "reason": "disabled"}))
            continue
        trace.append(CelTraceEvent(event="rule_tried", detail={"rule": label}))

        match_ctx: list[dict[str, Any]] = []
        capture_failed = False
        for cap_index, cap in enumerate(rule.captures):
            entry = _capture_entry(cap, bag)
            if not entry["ok"]:
                trace.append(
                    CelTraceEvent(
                        event="rule_not_matched",
                        detail={
                            "rule": label,
                            "reason": "capture_failed",
                            "capture_index": cap_index,
                            "attribute": cap.attribute,
                            "matcher_label": _matcher_label(cap),
                        },
                    )
                )
                capture_failed = True
                break
            match_ctx.append(entry)

        if capture_failed:
            continue

        activation = {
            "attributes": _to_cel_value(bag),
            "attr": _to_cel_value(bag),
            "match": _to_cel_value(match_ctx),
            "matches": _to_cel_value(match_ctx),
        }
        try:
            ast = env.compile(rule.expression)
            program = env.program(ast)
            out = program.evaluate(activation)
        except Exception as exc:  # celpy raises parser/runtime specific errors
            raise ImportRulesCelError(f"CEL rule {label} failed: {exc}") from exc

        payload = _normalize_rule_output(out, label)
        if payload is None:
            trace.append(CelTraceEvent(event="rule_not_matched", detail={"rule": label}))
            continue

        trace.append(CelTraceEvent(event="rule_matched", detail={"rule": label}))

        set_map = payload.get("set", {})
        if set_map is None:
            set_map = {}
        if not isinstance(set_map, dict):
            raise ImportRulesCelError(f"CEL rule {label}: `set` must be a map/object")
        for k, v in set_map.items():
            bag[str(k)] = v
            trace.append(CelTraceEvent(event="set_attribute", detail={"rule": label, "name": str(k), "value": v}))

        stop = payload.get("stop")
        drop = payload.get("drop")
        review = payload.get("review")

        if stop is not None and not isinstance(stop, str):
            raise ImportRulesCelError(f"CEL rule {label}: `stop` must be null or string")
        if drop is not None and not isinstance(drop, str):
            raise ImportRulesCelError(f"CEL rule {label}: `drop` must be null or string")
        if review is not None and not isinstance(review, str):
            raise ImportRulesCelError(f"CEL rule {label}: `review` must be null or string")

        if review is not None:
            require_review = True
            review_reason = review
            trace.append(CelTraceEvent(event="require_review", detail={"rule": label, "reason": review}))

        if drop is not None:
            dropped = True
            drop_reason = drop
            trace.append(CelTraceEvent(event="drop_row", detail={"rule": label, "reason": drop}))
            break

        if stop is not None:
            stopped_after_rule = label
            trace.append(CelTraceEvent(event="stop", detail={"rule": label, "reason": stop}))
            break

    return CelEvaluationResult(
        attributes=bag,
        dropped=dropped,
        drop_reason=drop_reason,
        require_review=require_review,
        review_reason=review_reason,
        stopped_after_rule=stopped_after_rule,
        trace=trace,
    )
