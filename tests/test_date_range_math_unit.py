"""Unit tests for Elasticsearch-style entry date expressions (#133)."""

from datetime import date, datetime, timezone

import pytest

from tallybadger.ledger.date_range_math import (
    QUICK_RANGE_CATALOGUE,
    DateRangeMathError,
    parse_entry_date_expression,
    quick_range_label_for,
    resolve_entry_date_range,
)

ANCHOR = datetime(2026, 5, 6, 14, 30, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("from_expr", "to_expr", "expected_start", "expected_end"),
    [
        ("now/y", "now", date(2026, 1, 1), date(2026, 5, 6)),
        ("now/M", "now", date(2026, 5, 1), date(2026, 5, 6)),
        ("now-1M/M", "now/M-1d", date(2026, 4, 1), date(2026, 4, 30)),
        ("now-1y/y", "now/y-1d", date(2025, 1, 1), date(2025, 12, 31)),
        ("now-7d", "now", date(2026, 4, 29), date(2026, 5, 6)),
        ("now-30d", "now", date(2026, 4, 6), date(2026, 5, 6)),
    ],
)
def test_catalogue_pairs_resolve_with_fixed_anchor(
    from_expr: str,
    to_expr: str,
    expected_start: date,
    expected_end: date,
) -> None:
    start, end = resolve_entry_date_range(from_expr, to_expr, anchor=ANCHOR)
    assert start == expected_start
    assert end == expected_end


def test_absolute_iso_date_expression() -> None:
    assert parse_entry_date_expression("2026-01-15", anchor=ANCHOR) == date(2026, 1, 15)


def test_unpadded_iso_calendar_date_literal_ignores_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unpadded month/day must not go through datemath UTC→local conversion."""
    monkeypatch.setenv("TALLYBADGER_TIMEZONE", "America/Los_Angeles")
    assert parse_entry_date_expression("2026-4-30", anchor=ANCHOR) == date(2026, 4, 30)
    assert parse_entry_date_expression("2026-04-30", anchor=ANCHOR) == date(2026, 4, 30)


def test_now_resolves_to_anchor_local_calendar_date() -> None:
    assert parse_entry_date_expression("now", anchor=ANCHOR) == date(2026, 5, 6)


def test_last_month_and_last_year_span_full_prior_periods() -> None:
    jan_anchor = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    month_start, month_end = resolve_entry_date_range(
        "now-1M/M",
        "now/M-1d",
        anchor=jan_anchor,
    )
    assert month_start == date(2025, 12, 1)
    assert month_end == date(2025, 12, 31)

    year_start, year_end = resolve_entry_date_range(
        "now-1y/y",
        "now/y-1d",
        anchor=jan_anchor,
    )
    assert year_start == date(2025, 1, 1)
    assert year_end == date(2025, 12, 31)


def test_inclusive_end_now_matches_entries_on_anchor_day() -> None:
    _, end = resolve_entry_date_range("now-7d", "now", anchor=ANCHOR)
    assert end == date(2026, 5, 6)


def test_from_after_to_raises() -> None:
    with pytest.raises(DateRangeMathError, match="after to_date"):
        resolve_entry_date_range("now", "now-7d", anchor=ANCHOR)


def test_empty_expression_raises() -> None:
    with pytest.raises(DateRangeMathError, match="must not be empty"):
        parse_entry_date_expression("   ", anchor=ANCHOR)


def test_quick_range_label_exact_match_after_trim() -> None:
    for entry in QUICK_RANGE_CATALOGUE:
        assert quick_range_label_for(entry.from_expr, entry.to_expr) == entry.label
        assert quick_range_label_for(f"  {entry.from_expr} ", f" {entry.to_expr} ") == entry.label


def test_quick_range_label_custom_when_not_catalogue() -> None:
    assert quick_range_label_for("now/y", "now-1d") is None
    assert quick_range_label_for("", "now") is None
    assert quick_range_label_for("now / y", "now") is None
