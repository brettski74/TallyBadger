"""Unit tests for snapshot format deprecation warning on import (#202)."""

import tallybadger.backup.snapshot as snapshot


def test_oldest_supported_import_format_version() -> None:
    assert snapshot.oldest_supported_import_format_version() == "1.6.0"


def test_format_deprecation_warning_none_for_current_export() -> None:
    assert snapshot.format_deprecation_warning(snapshot.export_format_version()) is None


def test_format_deprecation_warning_includes_required_version_facts() -> None:
    archive = "1.8.0"
    msg = snapshot.format_deprecation_warning(archive)
    assert msg is not None
    current = snapshot.export_format_version()
    oldest = snapshot.oldest_supported_import_format_version()
    assert current in msg
    assert archive in msg
    assert oldest in msg
    assert "deprecated" in msg.lower()
    assert "will be removed" in msg.lower()
    assert "re-export" in msg.lower()
    assert "recommended to ensure continued support" in msg.lower()
    assert "reload" not in msg.lower()


def test_format_deprecation_warning_tracks_patched_history() -> None:
    prev = snapshot.FORMAT_VERSION_HISTORY
    try:
        snapshot.FORMAT_VERSION_HISTORY = ("0.9.0", "1.0.0")
        msg = snapshot.format_deprecation_warning("0.9.0")
        assert msg is not None
        assert "0.9.0" in msg
        assert "1.0.0" in msg
        assert snapshot.oldest_supported_import_format_version() in msg
    finally:
        snapshot.FORMAT_VERSION_HISTORY = prev
