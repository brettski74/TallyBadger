"""Unit tests for PDF page size configuration."""

from tallybadger.api.pdf_page import (
    create_report_pdf,
    fpdf_page_format,
    resolved_pdf_page_size,
)


def test_pdf_page_size_defaults_to_us_letter() -> None:
    assert resolved_pdf_page_size() == "us-letter"
    assert resolved_pdf_page_size("a4") == "a4"
    assert fpdf_page_format("us-letter") == "letter"
    assert fpdf_page_format("a4") == "a4"


def test_create_report_pdf_honours_explicit_page_size() -> None:
    letter_pdf = create_report_pdf(page_size="us-letter")
    a4_pdf = create_report_pdf(page_size="a4")
    assert letter_pdf.w < letter_pdf.h
    assert a4_pdf.w < a4_pdf.h
    assert letter_pdf.w != a4_pdf.w


def test_create_report_pdf_landscape_uses_selected_page_size() -> None:
    letter_pdf = create_report_pdf(orientation="L", page_size="us-letter")
    a4_pdf = create_report_pdf(orientation="L", page_size="a4")
    assert letter_pdf.w > letter_pdf.h
    assert a4_pdf.w > a4_pdf.h
    assert letter_pdf.w != a4_pdf.w
