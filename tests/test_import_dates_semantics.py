"""Contract tests for CSV import date/datetime parsing (Pendulum).

These tests document the semantics users and templates rely on. If the project
switches away from Pendulum, keep this file aligned so behavior stays intentional.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tallybadger.import_dates import (
    import_parse_timezone,
    parse_import_date_string,
    parse_import_datetime_string,
)


def test_parse_date_iso_strict_valid() -> None:
    assert parse_import_date_string("2026-04-07", "YYYY-MM-DD") == date(2026, 4, 7)


def test_parse_date_yyyy_mm_dd_accepts_unpadded_month_day() -> None:
    """Pendulum treats month/day segments flexibly even when ``MM``/``DD`` appear in the pattern."""
    assert parse_import_date_string("2026-4-7", "YYYY-MM-DD") == date(2026, 4, 7)


def test_parse_date_iso_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid date"):
        parse_import_date_string("not-a-date", "YYYY-MM-DD")


def test_parse_date_iso_rejects_bad_month() -> None:
    with pytest.raises(ValueError, match="invalid date"):
        parse_import_date_string("2026-13-01", "YYYY-MM-DD")


def test_parse_date_us_m_d_lenient_single_digits() -> None:
    """Pendulum ``M`` / ``D`` allow one- or two-digit month and day."""
    assert parse_import_date_string("4/1/2026", "M/D/YYYY") == date(2026, 4, 1)
    assert parse_import_date_string("04/01/2026", "M/D/YYYY") == date(2026, 4, 1)


def test_parse_date_us_mm_dd_accepts_single_digit_segments() -> None:
    """Pendulum ``MM`` / ``DD`` still match one-digit month/day (library semantics)."""
    assert parse_import_date_string("4/7/2026", "MM/DD/YYYY") == date(2026, 4, 7)
    assert parse_import_date_string("04/07/2026", "MM/DD/YYYY") == date(2026, 4, 7)


def test_parse_date_year_first_lenient_m_d() -> None:
    assert parse_import_date_string("2026-4-7", "YYYY-M-D") == date(2026, 4, 7)


def test_parse_datetime_with_time_uses_configured_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TALLYBADGER_IMPORT_TZ", "UTC")
    dt = parse_import_datetime_string("2026-04-01 14:30:00", "YYYY-MM-DD HH:mm:ss")
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)
    assert dt.date() == date(2026, 4, 1)
    assert dt.hour == 14
    assert dt.minute == 30


def test_import_parse_timezone_skips_invalid_iana_and_uses_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TALLYBADGER_IMPORT_TZ", "NotA/Real_Zone")
    monkeypatch.setenv("TZ", "UTC")
    assert import_parse_timezone().name == "UTC"


def test_parse_date_blank_value() -> None:
    with pytest.raises(ValueError, match="blank"):
        parse_import_date_string("   ", "YYYY-MM-DD")


def test_parse_date_blank_format() -> None:
    with pytest.raises(ValueError, match="format is blank"):
        parse_import_date_string("2026-01-01", "")
