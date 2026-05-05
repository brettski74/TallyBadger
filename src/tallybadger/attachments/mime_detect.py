"""MIME type from magic bytes and filename extension (journal entry attachments)."""

from __future__ import annotations

import os


def detect_attachment_mime(data: bytes, original_filename: str | None) -> str:
    """Return MIME type using content sniffing first, then filename extension, else octet-stream."""
    sniffed = _sniff_mime(data)
    if sniffed is not None:
        return sniffed
    hinted = _extension_mime(original_filename)
    if hinted is not None:
        return hinted
    return "application/octet-stream"


def _sniff_mime(data: bytes) -> str | None:
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 5 and data[:5] == b"%PDF-":
        return "application/pdf"
    return None


def mime_type_to_snapshot_extension(mime_type: str) -> str:
    """Stable filename extension for backup ZIP members under ``attachments/``."""
    base = mime_type.split(";", 1)[0].strip().lower()
    if base == "image/jpeg":
        return "jpg"
    if base == "image/png":
        return "png"
    if base == "application/pdf":
        return "pdf"
    return "bin"


def _extension_mime(original_filename: str | None) -> str | None:
    if not original_filename:
        return None
    base = os.path.basename(original_filename.strip()).lower()
    if not base or "." not in base:
        return None
    ext = base.rsplit(".", 1)[-1]
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    if ext == "pdf":
        return "application/pdf"
    return None
