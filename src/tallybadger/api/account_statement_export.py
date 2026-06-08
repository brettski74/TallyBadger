"""CSV and PDF serialization for the Account Statement report."""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

from tallybadger.api.income_expense_export import _format_currency_usd, resolve_pdf_unicode_font_path
from tallybadger.ledger.models import AccountStatementReportOut, AccountStatementRowOut


def _decimal_csv(d: Decimal | None) -> str:
    if d is None:
        return ""
    return format(d, "f")


def _sanitize_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "-", value.strip(), flags=re.ASCII)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "account"


def account_statement_report_filename_stem(report: AccountStatementReportOut) -> str:
    name = _sanitize_filename_part(report.account.account_name)
    s = report.period.start_date.isoformat()
    e = report.period.end_date.isoformat()
    return f"account-statement_{name}_{s}_{e}"


def account_statement_report_csv_bytes(report: AccountStatementReportOut) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "entry_date",
            "summary",
            "account",
            "party",
            "debit",
            "credit",
            "balance",
            "row_kind",
        ],
    )
    w.writerow(["report", "account_statement", "", "", "", "", "", ""])
    w.writerow(["account_name", report.account.account_name, "", "", "", "", "", ""])
    w.writerow(["period_start", report.period.start_date.isoformat(), "", "", "", "", "", ""])
    w.writerow(["period_end", report.period.end_date.isoformat(), "", "", "", "", "", ""])
    for row in report.rows:
        w.writerow(_csv_row_cells(row))
    return buf.getvalue().encode("utf-8")


# Matches frontend --border (#e2e8f0).
_PDF_ROW_LINE_RGB = (226, 232, 240)
_PDF_ROW_LINE_WIDTH_MM = 0.15
_PDF_COLUMN_WEIGHTS = (22, 62, 42, 42, 28, 28, 28)
_PDF_TEXT_LINE_H = 4.0
_PDF_MIN_ROW_H = 7.0
_PDF_HEADER_H = 7.0


def _pdf_table_width(pdf: FPDF) -> float:
    return pdf.epw


def _pdf_column_widths(pdf: FPDF) -> tuple[float, ...]:
    table_width = _pdf_table_width(pdf)
    total_weight = sum(_PDF_COLUMN_WEIGHTS)
    return tuple(table_width * weight / total_weight for weight in _PDF_COLUMN_WEIGHTS)


def _pdf_column_x_offsets(col_widths: tuple[float, ...]) -> tuple[float, ...]:
    offsets: list[float] = [0.0]
    for width in col_widths[:-1]:
        offsets.append(offsets[-1] + width)
    return tuple(offsets)


def _pdf_text_block_height(pdf: FPDF, width: float, text: str, *, line_h: float) -> float:
    if not text:
        return 0.0
    measured = pdf.multi_cell(
        width,
        line_h,
        text=text,
        border=0,
        dry_run=True,
        output=MethodReturnValue.HEIGHT,
        new_x=XPos.RIGHT,
        new_y=YPos.TOP,
    )
    return float(measured)


def _pdf_draw_horizontal_rule(pdf: FPDF, x: float, y: float, width: float) -> None:
    pdf.set_draw_color(*_PDF_ROW_LINE_RGB)
    pdf.set_line_width(_PDF_ROW_LINE_WIDTH_MM)
    pdf.line(x, y, x + width, y)


def _pdf_draw_cell_text(
    pdf: FPDF,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    *,
    align: str,
    line_h: float,
) -> None:
    if not text:
        return
    content_h = max(line_h, _pdf_text_block_height(pdf, width, text, line_h=line_h))
    y_text = y + max(0.0, (height - content_h) / 2)
    pdf.set_xy(x, y_text)
    pdf.multi_cell(
        width,
        line_h,
        text=text,
        border=0,
        align=align,
        new_x=XPos.RIGHT,
        new_y=YPos.TOP,
    )


def _pdf_statement_row_height(
    pdf: FPDF,
    col_widths: tuple[float, ...],
    row: AccountStatementRowOut,
    *,
    line_h: float,
    min_row_h: float,
) -> float:
    row_height = min_row_h
    for width, text in (
        (col_widths[1], row.summary),
        (col_widths[2], row.counterparty_account or ""),
        (col_widths[3], row.party or ""),
    ):
        if text:
            row_height = max(row_height, _pdf_text_block_height(pdf, width, text, line_h=line_h))
    return row_height


def _pdf_draw_statement_row(
    pdf: FPDF,
    col_widths: tuple[float, ...],
    row: AccountStatementRowOut,
    *,
    row_height: float,
    line_h: float,
) -> None:
    x = pdf.l_margin
    y = pdf.get_y()
    table_width = _pdf_table_width(pdf)
    x_offsets = _pdf_column_x_offsets(col_widths)
    cell_specs: list[tuple[float, str, str]] = [
        (col_widths[0], row.entry_date.isoformat(), "L"),
        (col_widths[1], row.summary, "L"),
        (col_widths[2], row.counterparty_account or "", "L"),
        (col_widths[3], row.party or "", "L"),
    ]
    for amount in (row.debit, row.credit, row.balance):
        money_text = _format_currency_usd(amount) if amount is not None else ""
        cell_specs.append((col_widths[len(cell_specs)], money_text, "R"))

    for offset, (width, text, align) in zip(x_offsets, cell_specs, strict=True):
        _pdf_draw_cell_text(
            pdf, x + offset, y, width, row_height, text, align=align, line_h=line_h
        )

    _pdf_draw_horizontal_rule(pdf, x, y + row_height, table_width)
    pdf.set_xy(x, y + row_height)


def _csv_row_cells(row: AccountStatementRowOut) -> list[str]:
    return [
        row.entry_date.isoformat(),
        row.summary,
        row.counterparty_account or "",
        row.party or "",
        _decimal_csv(row.debit),
        _decimal_csv(row.credit),
        _decimal_csv(row.balance),
        row.row_kind,
    ]


def account_statement_report_pdf_bytes(report: AccountStatementReportOut) -> bytes:
    font_path = resolve_pdf_unicode_font_path()
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    pdf.add_font("ReportFont", "", str(font_path))
    pdf.c_margin = 1.0

    col_headers = ("Entry date", "Summary", "Account", "Party", "Debit", "Credit", "Balance")
    col_widths = _pdf_column_widths(pdf)
    bottom_margin = 15.0
    page_h = pdf.h

    def _draw_title_block() -> None:
        pdf.set_font("ReportFont", size=16)
        pdf.cell(0, 10, text=f"{report.account.account_name} Statement", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("ReportFont", size=11)
        pdf.cell(
            0,
            8,
            text=(
                f"Period: {report.period.start_date.isoformat()} – "
                f"{report.period.end_date.isoformat()}"
            ),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(2)

    def _draw_column_headers() -> None:
        x = pdf.l_margin
        y = pdf.get_y()
        table_width = _pdf_table_width(pdf)
        x_offsets = _pdf_column_x_offsets(col_widths)
        pdf.set_font("ReportFont", size=9)
        for offset, (label, width) in zip(x_offsets, zip(col_headers, col_widths, strict=True), strict=True):
            align = "R" if label in ("Debit", "Credit", "Balance") else "L"
            _pdf_draw_cell_text(
                pdf,
                x + offset,
                y,
                width,
                _PDF_HEADER_H,
                label,
                align=align,
                line_h=_PDF_TEXT_LINE_H,
            )
        _pdf_draw_horizontal_rule(pdf, x, y + _PDF_HEADER_H, table_width)
        pdf.set_xy(x, y + _PDF_HEADER_H)

    def _ensure_space(needed: float) -> None:
        nonlocal pdf
        if pdf.get_y() + needed > page_h - bottom_margin:
            pdf.add_page()
            _draw_column_headers()

    _draw_title_block()
    _draw_column_headers()

    pdf.set_font("ReportFont", size=8)
    for row in report.rows:
        row_height = _pdf_statement_row_height(
            pdf,
            col_widths,
            row,
            line_h=_PDF_TEXT_LINE_H,
            min_row_h=_PDF_MIN_ROW_H,
        )
        _ensure_space(row_height)
        _pdf_draw_statement_row(
            pdf,
            col_widths,
            row,
            row_height=row_height,
            line_h=_PDF_TEXT_LINE_H,
        )

    return bytes(pdf.output())
