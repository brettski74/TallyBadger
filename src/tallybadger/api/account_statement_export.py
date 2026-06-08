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


_PDF_TEXT_LINE_H = 4.0
_PDF_MIN_ROW_H = 7.0


def _pdf_wrapped_text_height(
    pdf: FPDF, width: float, text: str, *, line_h: float, min_h: float
) -> float:
    if not text:
        return min_h
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
    return max(min_h, float(measured))


def _pdf_draw_wrapped_text_cell(
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
    pdf.rect(x, y, width, height)
    if not text:
        return
    pdf.set_xy(x, y)
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
        row_height = max(
            row_height,
            _pdf_wrapped_text_height(pdf, width, text, line_h=line_h, min_h=min_row_h),
        )
    return row_height


def _pdf_draw_statement_row(
    pdf: FPDF,
    col_widths: tuple[float, ...],
    row: AccountStatementRowOut,
    *,
    row_height: float,
    line_h: float,
) -> None:
    summary = row.summary
    counterparty = row.counterparty_account or ""
    party = row.party or ""

    x = pdf.get_x()
    y = pdf.get_y()
    x_offsets = [0.0]
    for width in col_widths[:-1]:
        x_offsets.append(x_offsets[-1] + width)

    pdf.set_xy(x + x_offsets[0], y)
    pdf.cell(col_widths[0], row_height, text=row.entry_date.isoformat(), border=1)
    _pdf_draw_wrapped_text_cell(
        pdf, x + x_offsets[1], y, col_widths[1], row_height, summary, align="L", line_h=line_h
    )
    _pdf_draw_wrapped_text_cell(
        pdf,
        x + x_offsets[2],
        y,
        col_widths[2],
        row_height,
        counterparty,
        align="L",
        line_h=line_h,
    )
    _pdf_draw_wrapped_text_cell(
        pdf, x + x_offsets[3], y, col_widths[3], row_height, party, align="L", line_h=line_h
    )
    for col_index, amount in enumerate((row.debit, row.credit, row.balance), start=4):
        money_text = _format_currency_usd(amount) if amount is not None else ""
        pdf.set_xy(x + x_offsets[col_index], y)
        pdf.cell(col_widths[col_index], row_height, text=money_text, border=1, align="R")

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

    col_headers = ("Entry date", "Summary", "Account", "Party", "Debit", "Credit", "Balance")
    col_widths = (22.0, 62.0, 42.0, 42.0, 28.0, 28.0, 28.0)
    header_h = 7.0
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
        pdf.set_font("ReportFont", size=9)
        pdf.set_fill_color(230, 230, 230)
        for label, width in zip(col_headers, col_widths, strict=True):
            align = "R" if label in ("Debit", "Credit", "Balance") else "L"
            pdf.cell(width, header_h, text=label, border=1, fill=True, align=align)
        pdf.ln(header_h)
        pdf.set_fill_color(255, 255, 255)

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
