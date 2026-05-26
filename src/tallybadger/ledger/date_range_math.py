"""Elasticsearch-style date math for journal entry date filters (#133)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import NamedTuple

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

import arrow
import pendulum
from datemath import dm

from tallybadger.core.timezone import application_timezone_name


class DateRangeMathError(ValueError):
    """Raised when a date expression cannot be parsed or forms an invalid range."""


class QuickRangeCatalogueEntry(NamedTuple):
    label: str
    from_expr: str
    to_expr: str


QUICK_RANGE_CATALOGUE: tuple[QuickRangeCatalogueEntry, ...] = (
    QuickRangeCatalogueEntry("Year to date (YTD)", "now/y", "now"),
    QuickRangeCatalogueEntry("Month to date (MTD)", "now/M", "now"),
    # Last month: 1st through last day of the previous calendar month.
    QuickRangeCatalogueEntry("Last month", "now-1M/M", "now/M-1d"),
    # Last year: 1 Jan through 31 Dec of the previous calendar year.
    QuickRangeCatalogueEntry("Last year", "now-1y/y", "now/y-1d"),
    QuickRangeCatalogueEntry("Last 7 days", "now-7d", "now"),
    QuickRangeCatalogueEntry("Last 30 days", "now-30d", "now"),
)


def quick_range_label_for(from_expr: str | None, to_expr: str | None) -> str | None:
    """Return catalogue label when both expressions match exactly (trimmed), else ``None``."""
    if from_expr is None or to_expr is None:
        return None
    from_clean = from_expr.strip()
    to_clean = to_expr.strip()
    if not from_clean or not to_clean:
        return None
    for entry in QUICK_RANGE_CATALOGUE:
        if from_clean == entry.from_expr and to_clean == entry.to_expr:
            return entry.label
    return None


def _anchor_for_datemath(anchor: datetime | None) -> dict[str, str]:
    tz_name = application_timezone_name()
    kwargs: dict[str, str] = {"tz": tz_name}
    if anchor is None:
        return kwargs
    if anchor.tzinfo is None:
        localized = pendulum.instance(anchor, tz=tz_name)
    else:
        localized = pendulum.instance(anchor).in_timezone(tz_name)
    kwargs["now"] = arrow.get(localized.isoformat())
    return kwargs


def parse_entry_date_expression(expr: str, *, anchor: datetime | None = None) -> date:
    """Resolve one expression to an inclusive calendar date in the application timezone."""
    stripped = expr.strip()
    if not stripped:
        raise DateRangeMathError("date expression must not be empty")
    if _DATE_ONLY_RE.match(stripped):
        return date.fromisoformat(stripped)
    try:
        resolved = dm(stripped, **_anchor_for_datemath(anchor))
    except Exception as exc:
        raise DateRangeMathError(
            f"could not parse date expression {stripped!r}: {exc}",
        ) from exc
    tz_name = application_timezone_name()
    return resolved.to(tz_name).date()


def resolve_entry_date_range(
    from_expr: str,
    to_expr: str,
    *,
    anchor: datetime | None = None,
) -> tuple[date, date]:
    """Resolve a pair of expressions to inclusive ``(from_date, to_date)`` calendar bounds."""
    start = parse_entry_date_expression(from_expr, anchor=anchor)
    end = parse_entry_date_expression(to_expr, anchor=anchor)
    from_clean = from_expr.strip()
    to_clean = to_expr.strip()
    if start > end:
        raise DateRangeMathError(
            f"from_date expression {from_clean!r} resolves to {start.isoformat()} "
            f"which is after to_date expression {to_clean!r} ({end.isoformat()})",
        )
    return start, end


def parse_optional_entry_date_expression(
    expr: str | None,
    *,
    anchor: datetime | None = None,
) -> date | None:
    if expr is None:
        return None
    stripped = expr.strip()
    if not stripped:
        return None
    return parse_entry_date_expression(stripped, anchor=anchor)
