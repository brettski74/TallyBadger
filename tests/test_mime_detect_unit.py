from tallybadger.attachments.mime_detect import detect_attachment_mime

_MINIMAL_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_MINIMAL_PDF = b"%PDF-1.1\n1 0 obj<<>>endobj trailer<<>>\n%%EOF"


def test_detect_jpeg_by_magic() -> None:
    assert detect_attachment_mime(_MINIMAL_JPEG, "evil.png") == "image/jpeg"


def test_detect_png_by_magic() -> None:
    assert detect_attachment_mime(_PNG_SIG + b"rest", "file.txt") == "image/png"


def test_detect_pdf_by_magic() -> None:
    assert detect_attachment_mime(_MINIMAL_PDF, "wrong.jpg") == "application/pdf"


def test_detect_fallback_extension_when_no_magic() -> None:
    assert detect_attachment_mime(b"hello", "doc.pdf") == "application/pdf"
    assert detect_attachment_mime(b"hello", "x.JPEG") == "image/jpeg"
    assert detect_attachment_mime(b"hello", "x.PNG") == "image/png"


def test_detect_octet_stream_unknown() -> None:
    assert detect_attachment_mime(b"hello", "unknown.bin") == "application/octet-stream"
    assert detect_attachment_mime(b"hello", None) == "application/octet-stream"
