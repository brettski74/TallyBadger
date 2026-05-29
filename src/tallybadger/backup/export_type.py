"""Export scope resolution for snapshot export (#215)."""

from __future__ import annotations

CANONICAL_EXPORT_TYPES: tuple[str, ...] = ("complete", "configuration", "financial")
EXPORT_TYPE_API_ALIASES: frozenset[str] = frozenset({"full"})


class ExportTypeError(ValueError):
    """Unrecognized export_type."""


def normalize_export_type(export_type: str) -> str:
    """Map API ``export_type`` query values to a canonical export scope."""
    if export_type == "full":
        return "complete"
    if export_type in CANONICAL_EXPORT_TYPES:
        return export_type
    raise ExportTypeError(
        f"unrecognized export_type {export_type!r}; "
        f"expected one of {list(CANONICAL_EXPORT_TYPES)} or full"
    )
