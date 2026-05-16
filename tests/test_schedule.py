"""Unit tests for shared schedule generation."""

from __future__ import annotations

from datetime import date

import pytest

from tallybadger.ledger.schedule import DateIncrement, add_months, generate_schedule, safe_day


def test_safe_day_clamps_to_month_end() -> None:
    assert safe_day(2026, 1, 31) == date(2026, 1, 31)
    assert safe_day(2026, 2, 31) == date(2026, 2, 28)


def test_monthly_by_count_snow_removal_example() -> None:
    dates = generate_schedule(
        date(2025, 11, 1),
        increment=DateIncrement("months", 1),
        count=5,
    )
    assert dates == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
    ]


def test_monthly_by_end_inclusive_march() -> None:
    for end in (date(2026, 3, 1), date(2026, 3, 31)):
        dates = generate_schedule(
            date(2026, 1, 1),
            increment=DateIncrement("months", 1),
            end=end,
        )
        assert dates == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]


def test_monthly_by_end_includes_april_when_end_is_april_first() -> None:
    dates = generate_schedule(
        date(2026, 1, 1),
        increment=DateIncrement("months", 1),
        end=date(2026, 4, 1),
    )
    assert dates == [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
        date(2026, 4, 1),
    ]


def test_monthly_jan_31_steps_through_february() -> None:
    dates = generate_schedule(
        date(2026, 1, 31),
        increment=DateIncrement("months", 1),
        end=date(2026, 3, 31),
    )
    assert dates == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]


def test_monthly_no_date_before_start_when_anchor_after_start_day() -> None:
    dates = generate_schedule(
        date(2026, 11, 15),
        increment=DateIncrement("months", 1),
        day_of_month=1,
        count=3,
    )
    assert dates == [date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)]
    assert all(d >= date(2026, 11, 15) for d in dates)


def test_monthly_every_date_on_anchor_day() -> None:
    dates = generate_schedule(
        date(2026, 1, 15),
        increment=DateIncrement("months", 1),
        count=4,
    )
    assert all(d.day == 15 for d in dates)


def test_days_increment_exact_count() -> None:
    dates = generate_schedule(
        date(2026, 1, 1),
        increment=DateIncrement("days", 10),
        count=3,
    )
    assert dates == [date(2026, 1, 1), date(2026, 1, 11), date(2026, 1, 21)]


def test_weeks_increment_by_end() -> None:
    dates = generate_schedule(
        date(2026, 1, 1),
        increment=DateIncrement("weeks", 2),
        end=date(2026, 1, 29),
    )
    assert dates == [date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29)]


def test_count_mode_produces_exactly_n() -> None:
    dates = generate_schedule(
        date(2026, 5, 1),
        increment=DateIncrement("months", 1),
        count=1,
    )
    assert len(dates) == 1


def test_rejects_both_end_and_count() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        generate_schedule(
            date(2026, 1, 1),
            increment=DateIncrement("months", 1),
            end=date(2026, 3, 1),
            count=3,
        )


def test_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end must be on or after start"):
        generate_schedule(
            date(2026, 3, 1),
            increment=DateIncrement("months", 1),
            end=date(2026, 1, 1),
        )


def test_business_day_adjust_rolls_saturday_monthly() -> None:
    dates = generate_schedule(
        date(2026, 8, 1),
        increment=DateIncrement("months", 1),
        end=date(2026, 8, 31),
        business_day_adjust=True,
    )
    assert dates == [date(2026, 8, 3)]
