"""Unit tests for server-side export_type normalization (#215)."""

import pytest

from tallybadger.backup.export_type import (
    CANONICAL_EXPORT_TYPES,
    ExportTypeError,
    normalize_export_type,
)


@pytest.mark.parametrize("raw", [*CANONICAL_EXPORT_TYPES, "full"])
def test_normalize_export_type_accepts_canonical_and_full(raw: str) -> None:
    expected = "complete" if raw == "full" else raw
    assert normalize_export_type(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "fu",
        "f",
        "configuration-extra",
        "COMPLETE",
    ],
)
def test_normalize_export_type_rejects_invalid(raw: str) -> None:
    with pytest.raises(ExportTypeError):
        normalize_export_type(raw)
