"""Shared PDF page size helpers for financial report exports."""

from __future__ import annotations

from typing import Literal

from fpdf import FPDF

from tallybadger.ledger.models import PdfPageSizeKind

PdfOrientation = Literal["P", "L"]
_DEFAULT_PDF_PAGE_SIZE: PdfPageSizeKind = "us-letter"

_FPDF_PAGE_FORMAT: dict[PdfPageSizeKind, str] = {
    "us-letter": "letter",
    "a4": "a4",
}


def resolved_pdf_page_size(page_size: PdfPageSizeKind | None = None) -> PdfPageSizeKind:
    return page_size if page_size is not None else _DEFAULT_PDF_PAGE_SIZE


def fpdf_page_format(page_size: PdfPageSizeKind) -> str:
    return _FPDF_PAGE_FORMAT[page_size]


def create_report_pdf(
    *,
    orientation: PdfOrientation = "P",
    page_size: PdfPageSizeKind | None = None,
    unit: str = "mm",
) -> FPDF:
    resolved = resolved_pdf_page_size(page_size)
    return FPDF(orientation=orientation, unit=unit, format=fpdf_page_format(resolved))
