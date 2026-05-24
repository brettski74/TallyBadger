"""Pendulum-based parsing for CSV import date/datetime columns.

Import templates store *Pendulum* format strings (e.g. ``YYYY-MM-DD``, ``M/D/YYYY``).
Behaviors asserted in ``tests/test_import_dates_semantics.py`` are this project's
parsing contract; if swapping libraries, keep those tests green or update them
deliberately.
"""

from __future__ import annotations

from datetime import date, datetime

import pendulum
from pendulum.tz.timezone import Timezone

from tallybadger.core.timezone import application_timezone_name


def import_parse_timezone() -> Timezone:
    """Timezone for ``datetime`` CSV columns when the value has no UTC offset.

    Uses :func:`tallybadger.core.timezone.application_timezone_name` so import
    parsing and PostgreSQL ``CURRENT_DATE`` share the same calendar.
    """
    return pendulum.timezone(application_timezone_name())


def parse_import_date_string(value: str, fmt: str) -> date:
    """Strict parse using Pendulum; return a calendar :class:`datetime.date` only.

    Parsed at UTC midnight so the calendar day matches the input string (no local
    wall-clock shift for date-only fields).
    """
    text = value.strip()
    if not text:
        raise ValueError("value is blank")
    pattern = (fmt or "").strip()
    if not pattern:
        raise ValueError("date format is blank")
    try:
        dt = pendulum.from_format(text, pattern, tz=pendulum.timezone("UTC"))
    except ValueError as exc:
        raise ValueError(
            f"invalid date value {value!r} for Pendulum format {fmt!r}",
        ) from exc
    return dt.date()


def parse_import_datetime_string(value: str, fmt: str) -> datetime:
    """Strict parse; attach :func:`import_parse_timezone` when the string has no offset."""
    text = value.strip()
    if not text:
        raise ValueError("value is blank")
    pattern = (fmt or "").strip()
    if not pattern:
        raise ValueError("date format is blank")
    try:
        dt = pendulum.from_format(text, pattern, tz=import_parse_timezone())
    except ValueError as exc:
        raise ValueError(
            f"invalid datetime value {value!r} for Pendulum format {fmt!r}",
        ) from exc
    return dt
