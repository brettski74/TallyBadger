"""Tests for snapshot format_version import window (STYLE.md: last four history entries)."""

import tallybadger.backup.snapshot as snapshot


def test_supported_import_default_history() -> None:
    assert snapshot.supported_import_format_versions() == frozenset({"1.0.0", "1.1.0", "1.2.0"})


def test_supported_import_last_four_window() -> None:
    prev = snapshot.FORMAT_VERSION_HISTORY
    try:
        snapshot.FORMAT_VERSION_HISTORY = ("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0")
        assert snapshot.supported_import_format_versions() == frozenset(
            {"0.2.0", "0.3.0", "0.4.0", "0.5.0"},
        )
    finally:
        snapshot.FORMAT_VERSION_HISTORY = prev


def test_export_format_version_is_newest_in_history() -> None:
    prev = snapshot.FORMAT_VERSION_HISTORY
    try:
        snapshot.FORMAT_VERSION_HISTORY = ("0.9.0", "1.0.0")
        assert snapshot.export_format_version() == "1.0.0"
    finally:
        snapshot.FORMAT_VERSION_HISTORY = prev
