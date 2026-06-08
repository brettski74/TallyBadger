"""Shared PDF page size helpers for financial report exports."""

from __future__ import annotations

from typing import Literal

from fpdf import FPDF

from tallybadger.core.config import PdfPageSizeKind, get_settings

PdfOrientation = Literal["P", "L"]

_FPDF_PAGE_FORMAT: dict[PdfPageSizeKind, str] = {
    "us-letter": "letter",
    "a4": "a4",
}


def resolved_pdf_page_size(page_size: PdfPageSizeKind | None = None) -> PdfPageSizeKind:
    if page_size is not None:
        return page_size
    return get_settings().pdf_page_size


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
