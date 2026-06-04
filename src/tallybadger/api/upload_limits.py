"""HTTP-layer limits for untrusted uploads (#263)."""

from __future__ import annotations

from starlette.requests import Request

CONTENT_LENGTH_OVERHEAD_BYTES = 100 * 1024


class UploadTooLargeError(Exception):
    """Raised when an untrusted upload exceeds the configured byte limit."""

    def __init__(self, *, max_bytes: int, detail: str) -> None:
        self.max_bytes = max_bytes
        self.detail = detail
        super().__init__(detail)


def reject_oversize_content_length(request: Request, max_bytes: int) -> None:
    """Best-effort reject before reading the body when Content-Length is present."""
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        content_length = int(raw)
    except ValueError:
        return
    ceiling = max_bytes + CONTENT_LENGTH_OVERHEAD_BYTES
    if content_length > ceiling:
        raise UploadTooLargeError(
            max_bytes=max_bytes,
            detail=(
                f"request Content-Length {content_length} exceeds maximum upload size "
                f"of {max_bytes} bytes (plus {CONTENT_LENGTH_OVERHEAD_BYTES} bytes multipart overhead)"
            ),
        )


def read_upload_part_limited(file_obj: object, max_bytes: int) -> bytes:
    """Read an upload part until EOF; raise ``UploadTooLargeError`` if over ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    read = getattr(file_obj, "read")
    while True:
        chunk = read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(
                max_bytes=max_bytes,
                detail=f"attachment exceeds maximum size of {max_bytes} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)
