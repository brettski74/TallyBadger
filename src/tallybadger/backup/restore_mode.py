"""Restore mode resolution for snapshot import (#206)."""

from __future__ import annotations

CANONICAL_RESTORE_MODES: tuple[str, ...] = ("abort", "overwrite", "erase-reload")


class RestoreModeError(ValueError):
    """Unrecognized or ambiguous restore_mode."""


def resolve_restore_mode(restore_mode: str) -> str:
    """Return the canonical restore mode for the given user input."""
    raw = restore_mode.strip()
    if not raw:
        raise RestoreModeError("restore_mode must not be empty")

    lowered = raw.lower()
    matches = [mode for mode in CANONICAL_RESTORE_MODES if mode.startswith(lowered)]
    if not matches:
        raise RestoreModeError(
            f"unrecognized restore_mode {restore_mode!r}; "
            f"expected one of {list(CANONICAL_RESTORE_MODES)} "
            f"(prefixes allowed, e.g. a, o, e, erase-reload)"
        )
    if len(matches) > 1:
        raise RestoreModeError(
            f"ambiguous restore_mode {restore_mode!r}; matches {matches}"
        )
    return matches[0]
