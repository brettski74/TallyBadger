"""CSV and PDF serialization for the Account Statement report."""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal

from fpdf import FPDF
from fpdf.enums import XPos, YPos

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
    row_h = 7.0
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

    def _money_cell(width: float, amount: Decimal | None) -> None:
        text = _format_currency_usd(amount) if amount is not None else ""
        pdf.cell(width, row_h, text=text, border=1, align="R")

    _draw_title_block()
    _draw_column_headers()

    pdf.set_font("ReportFont", size=8)
    for row in report.rows:
        _ensure_space(row_h)
        pdf.cell(col_widths[0], row_h, text=row.entry_date.isoformat(), border=1)
        pdf.cell(col_widths[1], row_h, text=row.summary[:80], border=1)
        pdf.cell(col_widths[2], row_h, text=(row.counterparty_account or "")[:40], border=1)
        pdf.cell(col_widths[3], row_h, text=(row.party or "")[:40], border=1)
        _money_cell(col_widths[4], row.debit)
        _money_cell(col_widths[5], row.credit)
        _money_cell(col_widths[6], row.balance)
        pdf.ln(row_h)

    return bytes(pdf.output())
