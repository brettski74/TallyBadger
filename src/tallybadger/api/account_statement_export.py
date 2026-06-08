"""CSV and PDF serialization for the Account Statement report."""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

from tallybadger.api.income_expense_export import _format_currency_usd, resolve_pdf_unicode_font_path
from tallybadger.api.pdf_page import create_report_pdf
from tallybadger.ledger.models import AccountStatementReportOut, AccountStatementRowOut, PdfPageSizeKind


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
_PDF_TEXT_LINE_H = 4.0
_PDF_MIN_ROW_H = 7.0
_PDF_HEADER_H = 7.0
_PDF_BODY_FONT_SIZE = 8
_PDF_HEADER_FONT_SIZE = 9
_PDF_MIN_MONEY_FLOOR = Decimal("100000.00")
_PDF_MIN_TEXT_COL_EMS = 10
_PDF_WIDEST_ISO_DATE = "2099-12-31"


def _pdf_table_width(pdf: FPDF) -> float:
    return pdf.epw


def _pdf_em_width(pdf: FPDF) -> float:
    return pdf.get_string_width("0")


def _pdf_text_width(pdf: FPDF, text: str) -> float:
    return pdf.get_string_width(text)


def _pdf_cell_horizontal_padding(pdf: FPDF) -> float:
    return 2 * pdf.c_margin


def _pdf_average_char_counts(rows: list[AccountStatementRowOut]) -> tuple[float, float, float]:
    if not rows:
        return (1.0, 1.0, 1.0)
    summary_total = 0
    account_total = 0
    party_total = 0
    for row in rows:
        summary_total += len(row.summary)
        account_total += len(row.counterparty_account or "")
        party_total += len(row.party or "")
    count = len(rows)
    return (summary_total / count, account_total / count, party_total / count)


def _pdf_allocate_text_column_widths(
    *,
    available_width: float,
    avg_chars: tuple[float, float, float],
    em_width: float,
) -> tuple[float, float, float]:
    """Split width among Summary, Account, and Party using average char weights."""
    min_col_width = _PDF_MIN_TEXT_COL_EMS * em_width
    min_total = 3 * min_col_width

    if available_width <= 0:
        return (0.0, 0.0, 0.0)
    if available_width < min_total:
        third = available_width / 3.0
        return (third, third, third)

    weights = list(avg_chars)
    if sum(weights) <= 0:
        weights = [1.0, 1.0, 1.0]

    assigned: list[float | None] = [None, None, None]
    free_indices = [0, 1, 2]
    remaining = available_width

    while free_indices:
        weight_sum = sum(weights[index] for index in free_indices)
        if weight_sum <= 0:
            allocation = {index: remaining / len(free_indices) for index in free_indices}
        else:
            allocation = {
                index: remaining * weights[index] / weight_sum for index in free_indices
            }

        fixed_this_round = False
        for index in list(free_indices):
            if allocation[index] < min_col_width:
                assigned[index] = min_col_width
                remaining -= min_col_width
                free_indices.remove(index)
                fixed_this_round = True

        if not fixed_this_round:
            for index in free_indices:
                assigned[index] = allocation[index]
            break

    return tuple(width if width is not None else 0.0 for width in assigned)


def _pdf_largest_money_display_amount(rows: list[AccountStatementRowOut]) -> Decimal:
    largest = _PDF_MIN_MONEY_FLOOR
    for row in rows:
        for amount in (row.debit, row.credit, row.balance):
            if amount is not None:
                largest = max(largest, abs(amount))
    return largest


def _pdf_date_column_width(pdf: FPDF, rows: list[AccountStatementRowOut]) -> float:
    pdf.set_font("ReportFont", size=_PDF_BODY_FONT_SIZE)
    candidates = [_PDF_WIDEST_ISO_DATE]
    for row in rows:
        candidates.append(row.entry_date.isoformat())
    max_width = max(_pdf_text_width(pdf, text) for text in candidates)
    pdf.set_font("ReportFont", size=_PDF_HEADER_FONT_SIZE)
    max_width = max(max_width, _pdf_text_width(pdf, "Entry date"))
    return max_width + _pdf_cell_horizontal_padding(pdf)


def _pdf_money_column_width(pdf: FPDF, rows: list[AccountStatementRowOut]) -> float:
    display_amount = _pdf_largest_money_display_amount(rows)
    pdf.set_font("ReportFont", size=_PDF_BODY_FONT_SIZE)
    max_width = _pdf_text_width(pdf, _format_currency_usd(display_amount))
    pdf.set_font("ReportFont", size=_PDF_HEADER_FONT_SIZE)
    for label in ("Debit", "Credit", "Balance"):
        max_width = max(max_width, _pdf_text_width(pdf, label))
    return max_width + _pdf_cell_horizontal_padding(pdf)


def _pdf_column_widths(pdf: FPDF, report: AccountStatementReportOut) -> tuple[float, ...]:
    table_width = _pdf_table_width(pdf)
    date_width = _pdf_date_column_width(pdf, report.rows)
    money_width = _pdf_money_column_width(pdf, report.rows)
    text_available = table_width - date_width - (3 * money_width)
    if text_available < 0:
        fixed_budget = table_width * 0.65
        scale = fixed_budget / (date_width + (3 * money_width))
        date_width *= scale
        money_width *= scale
        text_available = table_width - date_width - (3 * money_width)
    pdf.set_font("ReportFont", size=_PDF_BODY_FONT_SIZE)
    summary_width, account_width, party_width = _pdf_allocate_text_column_widths(
        available_width=max(0.0, text_available),
        avg_chars=_pdf_average_char_counts(report.rows),
        em_width=_pdf_em_width(pdf),
    )
    return (
        date_width,
        summary_width,
        account_width,
        party_width,
        money_width,
        money_width,
        money_width,
    )


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


def _pdf_draw_single_line_cell(
    pdf: FPDF,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    *,
    align: str,
) -> None:
    pdf.set_xy(x, y)
    pdf.cell(width, height, text=text, border=0, align=align)


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
        if offset == x_offsets[0] or offset >= x_offsets[4]:
            _pdf_draw_single_line_cell(
                pdf, x + offset, y, width, row_height, text, align=align
            )
        else:
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


def account_statement_report_pdf_bytes(
    report: AccountStatementReportOut,
    *,
    page_size: PdfPageSizeKind | None = None,
) -> bytes:
    font_path = resolve_pdf_unicode_font_path()
    pdf = create_report_pdf(orientation="L", page_size=page_size)
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    pdf.add_font("ReportFont", "", str(font_path))
    pdf.c_margin = 1.0

    col_headers = ("Entry date", "Summary", "Account", "Party", "Debit", "Credit", "Balance")
    pdf.set_font("ReportFont", size=_PDF_BODY_FONT_SIZE)
    col_widths = _pdf_column_widths(pdf, report)
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
        pdf.set_font("ReportFont", size=_PDF_HEADER_FONT_SIZE)
        for offset, (label, width) in zip(x_offsets, zip(col_headers, col_widths, strict=True), strict=True):
            align = "R" if label in ("Debit", "Credit", "Balance") else "L"
            if offset == x_offsets[0] or offset >= x_offsets[4]:
                _pdf_draw_single_line_cell(
                    pdf,
                    x + offset,
                    y,
                    width,
                    _PDF_HEADER_H,
                    label,
                    align=align,
                )
            else:
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

    pdf.set_font("ReportFont", size=_PDF_BODY_FONT_SIZE)
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
