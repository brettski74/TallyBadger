"""Resolve Elasticsearch-style date math expressions for UI display (#133)."""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime

import pendulum
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from tallybadger.core.timezone import application_timezone_name
from tallybadger.ledger.date_range_math import (
    DateRangeMathError,
    parse_entry_date_expression,
    resolve_entry_date_range,
)

router = APIRouter(tags=["date-range"])


class DateRangeResolveResponse(BaseModel):
    date: DateType | None = None
    from_date: DateType | None = None
    to_date: DateType | None = None


def _parse_anchor(anchor: str | None) -> datetime | None:
    if anchor is None:
        return None
    stripped = anchor.strip()
    if not stripped:
        return None
    try:
        parsed = pendulum.parse(stripped)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"could not parse anchor {stripped!r}: {exc}",
        ) from exc
    tz_name = application_timezone_name()
    return parsed.in_timezone(tz_name)


@router.get("/date-range/resolve", response_model=DateRangeResolveResponse)
def resolve_date_range(
    expr: str | None = Query(
        default=None,
        description="Single date math expression (mutually exclusive with from/to pair).",
    ),
    from_date: str | None = Query(
        default=None,
        alias="from",
        description="Range start expression (use with ``to``).",
    ),
    to_date: str | None = Query(
        default=None,
        alias="to",
        description="Range end expression (use with ``from``).",
    ),
    anchor: str | None = Query(
        default=None,
        description="Optional ISO datetime anchor for tests (defaults to current time).",
    ),
) -> DateRangeResolveResponse:
    anchor_dt = _parse_anchor(anchor)
    has_expr = expr is not None and expr.strip() != ""
    has_from = from_date is not None and from_date.strip() != ""
    has_to = to_date is not None and to_date.strip() != ""

    if has_expr and (has_from or has_to):
        raise HTTPException(
            status_code=422,
            detail="provide either expr or both from and to, not both",
        )
    if has_from != has_to:
        raise HTTPException(
            status_code=422,
            detail="from and to must both be provided for a range",
        )
    if not has_expr and not has_from:
        raise HTTPException(
            status_code=422,
            detail="provide expr or both from and to",
        )

    try:
        if has_expr:
            assert expr is not None
            return DateRangeResolveResponse(
                date=parse_entry_date_expression(expr, anchor=anchor_dt),
            )
        assert from_date is not None and to_date is not None
        start, end = resolve_entry_date_range(
            from_date,
            to_date,
            anchor=anchor_dt,
        )
        return DateRangeResolveResponse(from_date=start, to_date=end)
    except DateRangeMathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
