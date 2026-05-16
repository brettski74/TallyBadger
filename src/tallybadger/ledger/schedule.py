"""Shared date schedule generation for cheque series and accrual plans."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

IncrementUnit = Literal["days", "weeks", "months"]


@dataclass(frozen=True, slots=True)
class DateIncrement:
    unit: IncrementUnit
    n: int

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ValueError("increment n must be at least 1")


def safe_day(year: int, month: int, day_of_month: int) -> date:
    """Calendar day clamped to the last day of the month when needed."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day_of_month, last))


def roll_forward_weekend(value: date) -> date:
    if value.weekday() == 5:
        return value + timedelta(days=2)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _anchor_day(start: date, day_of_month: int | None) -> int:
    return day_of_month if day_of_month is not None else start.day


def _on_monthly_anchor(value: date, anchor_day: int) -> bool:
    return value == safe_day(value.year, value.month, anchor_day)


def _first_monthly_on_or_after(start: date, anchor_day: int) -> date:
    candidate = safe_day(start.year, start.month, anchor_day)
    if candidate >= start:
        return candidate
    year, month = start.year, start.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return safe_day(year, month, anchor_day)


def add_days(value: date, n: int) -> date:
    return value + timedelta(days=n)


def add_weeks(value: date, n: int) -> date:
    return add_days(value, 7 * n)


def add_months(value: date, n: int, *, anchor_day: int) -> date:
    """Advance by n calendar months, landing on anchor_day (month-end clamped)."""
    year, month = value.year, value.month
    month += n
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return safe_day(year, month, anchor_day)


def advance_date(value: date, increment: DateIncrement, *, anchor_day: int) -> date:
    if increment.unit == "days":
        return add_days(value, increment.n)
    if increment.unit == "weeks":
        return add_weeks(value, increment.n)
    return add_months(value, increment.n, anchor_day=anchor_day)


def _first_date(start: date, increment: DateIncrement, anchor_day: int) -> date:
    if increment.unit == "months":
        return _first_monthly_on_or_after(start, anchor_day)
    return start


def _apply_adjustment(value: date, *, business_day_adjust: bool, increment: DateIncrement, anchor_day: int) -> date:
    if not business_day_adjust:
        return value
    if increment.unit == "months" and _on_monthly_anchor(value, anchor_day):
        return roll_forward_weekend(value)
    return value


def generate_schedule(
    start: date,
    *,
    increment: DateIncrement,
    day_of_month: int | None = None,
    end: date | None = None,
    count: int | None = None,
    business_day_adjust: bool = False,
) -> list[date]:
    """Build a schedule of dates on or after start, stepping by increment.

    Exactly one of end or count must be provided. When increment.unit is months,
  day_of_month defaults to start.day. Each returned date lies on that day-of-month
    (after optional weekend roll-forward). No date is before start or after end.
    """
    if (end is None) == (count is None):
        raise ValueError("provide exactly one of end or count")
    if end is not None and end < start:
        raise ValueError("end must be on or after start")
    if count is not None and count < 1:
        raise ValueError("count must be at least 1")

    anchor = _anchor_day(start, day_of_month)
    if increment.unit == "months" and not 1 <= anchor <= 31:
        raise ValueError("day_of_month must be between 1 and 31")

    dates: list[date] = []
    current = _first_date(start, increment, anchor)

    while True:
        if current < start:
            raise ValueError("schedule produced a date before start")
        if end is not None and current > end:
            break
        adjusted = _apply_adjustment(
            current,
            business_day_adjust=business_day_adjust,
            increment=increment,
            anchor_day=anchor,
        )
        if end is not None and adjusted > end:
            break
        dates.append(adjusted)
        if count is not None and len(dates) >= count:
            break
        current = advance_date(current, increment, anchor_day=anchor)

    if count is not None and len(dates) != count:
        raise ValueError(f"schedule produced {len(dates)} dates, expected {count}")

    return dates
