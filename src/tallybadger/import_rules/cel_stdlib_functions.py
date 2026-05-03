"""CEL extension functions for import rules: dates, numbers, maps, accounts (#50)."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import Any

from celpy import celtypes
from celpy.evaluation import CELFunction, Result

from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.models import AccountOut


def _cel_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, celtypes.StringType):
        return str(value).strip()
    return str(value).strip()


def _parse_iso_calendar_date(value: Any) -> date:
    """Parse CEL / attribute values to a calendar date (see docs #50)."""
    if value is None:
        raise ImportRulesCelError("date helper: value is null")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, celtypes.StringType):
        s = str(value).strip()
        if not s:
            raise ImportRulesCelError("date helper: blank date string")
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            try:
                return date.fromisoformat(s)
            except ValueError as exc:
                raise ImportRulesCelError(f"date helper: unparseable date {s!r}") from exc
        normalized = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError as exc:
            raise ImportRulesCelError(f"date helper: unparseable date-time {s!r}") from exc
    raise ImportRulesCelError(f"date helper: expected date or timestamp, got {type(value).__name__}")


def _cel_int_param(
    value: Any,
    *,
    label: str,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    if isinstance(value, celtypes.IntType):
        n = int(value)
    elif isinstance(value, celtypes.UintType):
        n = int(value)
    elif isinstance(value, celtypes.DoubleType):
        f = float(value)
        if not f.is_integer():
            raise ImportRulesCelError(f"{label}: must be a whole number")
        n = int(f)
    else:
        raise ImportRulesCelError(f"{label}: expected integer, got {type(value).__name__}")
    if min_value is not None and n < min_value:
        raise ImportRulesCelError(f"{label}: must be >= {min_value}")
    if max_value is not None and n > max_value:
        raise ImportRulesCelError(f"{label}: must be <= {max_value}")
    return n


def _decode_lookup_key(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, celtypes.BoolType):
        return "true" if bool(val) else "false"
    if isinstance(val, celtypes.IntType):
        return str(int(val))
    if isinstance(val, celtypes.UintType):
        return str(int(val))
    if isinstance(val, celtypes.DoubleType):
        f = float(val)
        if f.is_integer():
            return str(int(f))
        return str(f)
    if isinstance(val, celtypes.StringType):
        return str(val)
    return str(val)


def _map_to_str_keyed_cel_values(m: Any) -> dict[str, Any] | None:
    if isinstance(m, celtypes.MapType):
        raw = dict(m)
        return {str(k): v for k, v in raw.items()}
    if isinstance(m, dict):
        return {str(k): v for k, v in m.items()}
    return None


def build_stdlib_cel_functions(
    attributes: dict[str, Any],
    accounts: list[AccountOut] | None,
) -> dict[str, CELFunction]:
    """Return cel-python bindings for generic import CEL helpers (#50)."""
    bag = attributes
    acct_rows = accounts or []
    by_trimmed_name: dict[str, AccountOut] = {}
    for a in acct_rows:
        by_trimmed_name[a.name.strip()] = a

    def cel_abs(v: Any) -> Result:
        if isinstance(v, celtypes.IntType):
            return celtypes.IntType(abs(int(v)))
        if isinstance(v, celtypes.UintType):
            return v
        if isinstance(v, celtypes.DoubleType):
            return celtypes.DoubleType(abs(float(v)))
        if isinstance(v, celtypes.StringType):
            s = str(v).strip()
            if not s:
                raise ImportRulesCelError("abs: blank string is not numeric")
            if re.fullmatch(r"-?\d+", s):
                return celtypes.IntType(abs(int(s)))
            try:
                return celtypes.DoubleType(abs(float(s)))
            except ValueError as exc:
                raise ImportRulesCelError(f"abs: not a numeric string: {s!r}") from exc
        raise ImportRulesCelError(f"abs: expected number, got {type(v).__name__}")

    def day(d: Any) -> Result:
        parsed = _parse_iso_calendar_date(d)
        return celtypes.IntType(parsed.day)

    def month_fn(d: Any) -> Result:
        parsed = _parse_iso_calendar_date(d)
        return celtypes.IntType(parsed.month)

    def decode_fn(val: Any, m: Any, default_val: Any) -> Result:
        keyed = _map_to_str_keyed_cel_values(m)
        if keyed is None:
            return default_val
        lk = _decode_lookup_key(val)
        if lk is None:
            return default_val
        if lk in keyed:
            return keyed[lk]
        stripped = lk.strip()
        if stripped != lk and stripped in keyed:
            return keyed[stripped]
        return default_val

    def defined_fn(key: Any) -> Result:
        k = _cel_str(key)
        if not k:
            return celtypes.BoolType(False)
        if k not in bag:
            return celtypes.BoolType(False)
        cur = bag.get(k)
        if cur is None:
            return celtypes.BoolType(False)
        if cur == "":
            return celtypes.BoolType(False)
        return celtypes.BoolType(True)

    def account_type_fn(name: Any) -> Result:
        key = _cel_str(name)
        if not key:
            raise ImportRulesCelError("account_type: account name is blank")
        acc = by_trimmed_name.get(key)
        if acc is None:
            raise ImportRulesCelError(f"account_type: unknown account {key!r}")
        if not acc.is_active:
            raise ImportRulesCelError(f"account_type: inactive account {key!r}")
        return celtypes.StringType(acc.type)

    def match_date_fn(d: Any, n: Any, t: Any) -> Result:
        parsed = _parse_iso_calendar_date(d)
        dom = parsed.day
        n_day = _cel_int_param(n, label="match_date day-of-month", min_value=1, max_value=31)
        tol = _cel_int_param(t, label="match_date tolerance", min_value=0)
        dim = calendar.monthrange(parsed.year, parsed.month)[1]
        low = max(1, n_day - tol)
        high = min(dim, n_day + tol)
        return celtypes.BoolType(low <= dom <= high)

    return {
        "abs": cel_abs,
        "day": day,
        "month": month_fn,
        "decode": decode_fn,
        "defined": defined_fn,
        "account_type": account_type_fn,
        "match_date": match_date_fn,
    }
