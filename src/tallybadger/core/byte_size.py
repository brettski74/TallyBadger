"""Parse human byte sizes (bytes, k, M) for configuration fields."""

from __future__ import annotations

import re

_BYTE_SIZE_PATTERN = re.compile(r"^\s*(\d+)\s*([kKmM]?)\s*$")


def parse_byte_size(value: str | int) -> int:
    """Return a positive byte count.

    Accepts a non-negative int (bytes), or a string: digits only, or digits + ``k`` / ``K``
    (× 2^10) or ``m`` / ``M`` (× 2^20). Whitespace around the value is ignored.
    """
    if isinstance(value, int):
        if value <= 0:
            msg = "byte size must be a positive integer"
            raise ValueError(msg)
        return value
    match = _BYTE_SIZE_PATTERN.match(value.strip())
    if not match:
        msg = (
            "invalid byte size: expected a positive integer, optionally suffixed with "
            "'k' (×1024) or 'M' (×1048576)"
        )
        raise ValueError(msg)
    n = int(match.group(1))
    if n <= 0:
        msg = "byte size must be a positive integer"
        raise ValueError(msg)
    suffix = match.group(2)
    if suffix in ("k", "K"):
        return n * 1024
    if suffix in ("m", "M"):
        return n * 1024 * 1024
    if suffix == "":
        return n
    msg = "invalid byte size suffix"
    raise ValueError(msg)
