from __future__ import annotations

import json
import re
from copy import copy
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from celpy import Environment, celtypes
from celpy.evaluation import CELEvalError, CELFunction, Result

from tallybadger.import_rules.cel_models import (
    CelDebugEvent,
    CelEvaluationResult,
    CelRegexCapture,
    CelRule,
    CelRuleSet,
    CelTraceEvent,
)
from tallybadger.import_rules.cel_cheque_functions import build_cheque_cel_functions
from tallybadger.import_rules.cel_party_functions import build_party_cel_functions
from tallybadger.import_rules.cel_stdlib_functions import build_stdlib_cel_functions
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.models import AccountOut, ChequeOut, PartyOut


class _CelAttributeBagUnset:
    """Singleton: `set` map value meaning remove key from the row attribute bag (#57)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<unset>"


CEL_ATTRIBUTE_BAG_UNSET = _CelAttributeBagUnset()


class CelUnsetValue(celtypes.StringType):
    """CEL return type for `unset()` only; distinguished from ordinary strings in `_from_cel_value`."""

    __slots__ = ()


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
    if isinstance(value, CelUnsetValue):
        return CEL_ATTRIBUTE_BAG_UNSET
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


def _jsonable_debug_snapshot(value: Any) -> Any:
    """Make a JSON-friendly snapshot for debug records; never raises."""
    if value is CEL_ATTRIBUTE_BAG_UNSET:
        return "<unset>"
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            try:
                out[str(k)] = _jsonable_debug_snapshot(v)
            except Exception:
                out[str(k)] = repr(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_jsonable_debug_snapshot(v) for v in value]
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)
    return value


def _debug_value_snapshot(cel_arg: Any) -> Any:
    """Serialize a CEL value for `debug` records; failures fall back to repr (never raises)."""
    try:
        py = _from_cel_value(cel_arg)
    except Exception:
        try:
            return repr(cel_arg)
        except Exception:
            return "<debug serialization failed>"
    try:
        return _jsonable_debug_snapshot(py)
    except Exception:
        try:
            return repr(py)
        except Exception:
            return "<debug serialization failed>"


def _build_debug_cel_function(
    records: list[CelDebugEvent],
    current_rule_label: list[str],
    row_number: int | None,
) -> CELFunction:
    """Single-arg `debug(x)` — returns x unchanged and appends a CelDebugEvent."""

    def debug_fn(arg: Any) -> Result:
        snap = _debug_value_snapshot(arg)
        label = current_rule_label[0] if current_rule_label else ""
        try:
            records.append(CelDebugEvent(rule=label, value=snap, row_number=row_number))
        except Exception:
            records.append(
                CelDebugEvent(rule=label or "?", value="<debug record failed>", row_number=row_number),
            )
        return arg

    return debug_fn


def _build_unset_cel_function() -> CELFunction:
    """Zero-arg `unset()` — value marks removal of the enclosing `set` map key (#57)."""

    def unset_fn() -> Result:
        return CelUnsetValue("")

    return unset_fn


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


def _reraise_celeval_as_import_rules(err: CELEvalError) -> None:
    """cel-python records some failures as CELEvalError values embedded in map results."""
    if len(err.args) >= 2 and err.args[1] is ImportRulesCelError:
        inner = err.args[2]
        text = inner[0] if isinstance(inner, tuple) and inner else str(inner)
        raise ImportRulesCelError(str(text)) from err
    if err.args and err.args[0] == "no such key" and len(err.args) >= 3:
        key = err.args[2]
        raise ImportRulesCelError(f"CEL reference error: no such key {key!r}") from err
    raise ImportRulesCelError(f"CEL evaluation failed: {err.args[0] if err.args else err!r}") from err


def _walk_cel_result_for_wrapped_domain_errors(value: Any) -> None:
    if isinstance(value, CELEvalError):
        _reraise_celeval_as_import_rules(value)
        return
    if isinstance(value, celtypes.MapType):
        for v in dict(value).values():
            _walk_cel_result_for_wrapped_domain_errors(v)
        return
    if isinstance(value, dict):
        for v in value.values():
            _walk_cel_result_for_wrapped_domain_errors(v)
        return
    if isinstance(value, celtypes.ListType):
        for v in list(value):
            _walk_cel_result_for_wrapped_domain_errors(v)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _walk_cel_result_for_wrapped_domain_errors(v)


def _normalize_rule_output(result: Any, rule_label: str) -> dict[str, Any] | None:
    py = _from_cel_value(result)
    if py is None:
        return None
    if not isinstance(py, dict):
        raise ImportRulesCelError(
            f"CEL rule {rule_label} returned {type(py).__name__}; expected map/object or null",
        )
    return py


def _append_review_string(rule_label: str, value: Any, acc: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ImportRulesCelError(f"CEL rule {rule_label}: `review` must be null or a string")
    text = value.strip()
    if not text:
        raise ImportRulesCelError(
            f"CEL rule {rule_label}: `review` must be a non-empty string when provided",
        )
    acc.append(text)


def _append_review_messages_list(rule_label: str, value: Any, acc: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, (list, tuple)):
        raise ImportRulesCelError(
            f"CEL rule {rule_label}: `review-messages` must be null or a list",
        )
    for i, item in enumerate(value):
        if item is None:
            continue
        if not isinstance(item, str):
            raise ImportRulesCelError(
                f"CEL rule {rule_label}: `review-messages[{i}]` must be a string",
            )
        s = item.strip()
        if s:
            acc.append(s)


def evaluate_cel(
    rule_set: CelRuleSet,
    attributes: dict[str, Any],
    *,
    parties: list[PartyOut] | None = None,
    accounts: list[AccountOut] | None = None,
    cheques: list[ChequeOut] | None = None,
    row_number: int | None = None,
    default_account_name: str | None = None,
) -> CelEvaluationResult:
    bag: dict[str, Any] = {k: copy(v) if isinstance(v, (list, dict)) else v for k, v in attributes.items()}
    if (
        default_account_name is not None
        and str(default_account_name).strip() != ""
        and "default-account" not in bag
    ):
        bag["default-account"] = str(default_account_name).strip()
    trace: list[CelTraceEvent] = []
    debug_records: list[CelDebugEvent] = []
    current_rule_label: list[str] = [""]
    party_functions = build_party_cel_functions(parties or [])
    stdlib_functions = build_stdlib_cel_functions(bag, accounts)
    cheque_functions = build_cheque_cel_functions(cheques, accounts, parties)
    debug_fn = _build_debug_cel_function(debug_records, current_rule_label, row_number)
    unset_fn = _build_unset_cel_function()
    cel_functions: dict[str, CELFunction] = {
        **party_functions,
        **stdlib_functions,
        **cheque_functions,
        "debug": debug_fn,
        "unset": unset_fn,
    }
    dropped = False
    drop_reason: str | None = None
    review_messages: list[str] = []
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
            current_rule_label[0] = label
            ast = env.compile(rule.expression)
            program = env.program(ast, functions=cel_functions)
            out = program.evaluate(activation)
        except Exception as exc:  # celpy raises parser/runtime specific errors
            raise ImportRulesCelError(f"CEL rule {label} failed: {exc}") from exc

        try:
            _walk_cel_result_for_wrapped_domain_errors(out)
        except ImportRulesCelError as exc:
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
            key = str(k)
            if key == "review":
                before = len(review_messages)
                _append_review_string(label, v, review_messages)
                if len(review_messages) > before:
                    trace.append(
                        CelTraceEvent(
                            event="require_review",
                            detail={"rule": label, "review": review_messages[-1]},
                        ),
                    )
                continue
            if key == "review-messages":
                before = len(review_messages)
                _append_review_messages_list(label, v, review_messages)
                added = review_messages[before:]
                if added:
                    trace.append(
                        CelTraceEvent(
                            event="require_review_messages",
                            detail={"rule": label, "messages": added},
                        ),
                    )
                continue
            if v is CEL_ATTRIBUTE_BAG_UNSET:
                bag.pop(key, None)
                trace.append(CelTraceEvent(event="remove_attribute", detail={"rule": label, "name": key}))
            else:
                bag[key] = v
                trace.append(CelTraceEvent(event="set_attribute", detail={"rule": label, "name": key, "value": v}))

        stop = payload.get("stop")
        drop = payload.get("drop")

        if stop is not None and not isinstance(stop, str):
            raise ImportRulesCelError(f"CEL rule {label}: `stop` must be null or string")
        if drop is not None and not isinstance(drop, str):
            raise ImportRulesCelError(f"CEL rule {label}: `drop` must be null or string")

        before_top = len(review_messages)
        _append_review_string(label, payload.get("review"), review_messages)
        if len(review_messages) > before_top:
            trace.append(
                CelTraceEvent(
                    event="require_review",
                    detail={"rule": label, "review": review_messages[-1]},
                ),
            )
        before_list = len(review_messages)
        _append_review_messages_list(label, payload.get("review-messages"), review_messages)
        added_list = review_messages[before_list:]
        if added_list:
            trace.append(
                CelTraceEvent(
                    event="require_review_messages",
                    detail={"rule": label, "messages": added_list},
                ),
            )

        bag.pop("review", None)
        bag.pop("review-messages", None)

        if drop is not None:
            dropped = True
            drop_reason = drop
            trace.append(CelTraceEvent(event="drop_row", detail={"rule": label, "reason": drop}))
            break

        if stop is not None:
            stopped_after_rule = label
            trace.append(CelTraceEvent(event="stop", detail={"rule": label, "reason": stop}))
            break

    bag.pop("review", None)
    bag.pop("review-messages", None)

    debug_out: list[CelDebugEvent] | None = debug_records if debug_records else None
    return CelEvaluationResult(
        attributes=bag,
        dropped=dropped,
        drop_reason=drop_reason,
        review_messages=review_messages,
        stopped_after_rule=stopped_after_rule,
        trace=trace,
        debug=debug_out,
    )
