"""Unit tests for server-side restore_mode resolution (#206)."""

import pytest

from tallybadger.backup.restore_mode import (
    RestoreModeError,
    resolve_restore_mode,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a", "abort"),
        ("abort", "abort"),
        ("o", "overwrite"),
        ("overwrite", "overwrite"),
        ("e", "erase-reload"),
        ("erase-", "erase-reload"),
        ("erase-reload", "erase-reload"),
        ("ERASE-RELOAD", "erase-reload"),
    ],
)
def test_resolve_restore_mode_accepts_prefixes(raw: str, expected: str) -> None:
    assert resolve_restore_mode(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "z",
        "erase-spice-girls-music",
        "overwrite-extra",
        "erase_reload",
    ],
)
def test_resolve_restore_mode_rejects_invalid(raw: str) -> None:
    with pytest.raises(RestoreModeError):
        resolve_restore_mode(raw)
