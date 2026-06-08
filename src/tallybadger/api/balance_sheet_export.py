"""CSV and PDF serialization for the Balance Sheet report."""

from __future__ import annotations

import csv
import io
from decimal import ROUND_HALF_UP, Decimal

from fpdf.enums import XPos, YPos

from tallybadger.api.income_expense_export import resolve_pdf_unicode_font_path
from tallybadger.api.pdf_page import create_report_pdf
from tallybadger.core.config import PdfPageSizeKind
from tallybadger.ledger.models import BalanceSheetReportOut


def _decimal_csv(d: Decimal) -> str:
    return format(d, "f")


def _format_currency_usd(d: Decimal) -> str:
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if q < 0:
        return f"-${format(abs(q), ',.2f')}"
    return f"${format(q, ',.2f')}"


def balance_sheet_report_filename_stem(report: BalanceSheetReportOut) -> str:
    return f"balance-sheet_{report.period.as_of_date.isoformat()}"


def balance_sheet_report_csv_bytes(report: BalanceSheetReportOut) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["field", "value", "amount"])
    w.writerow(["report", "balance_sheet", ""])
    w.writerow(["as_of_date", report.period.as_of_date.isoformat(), ""])
    w.writerow(["exclude_requires_review", str(report.exclude_requires_review).lower(), ""])
    if report.preset:
        w.writerow(["preset", report.preset, ""])

    for row in report.assets.accounts:
        w.writerow(["asset", row.account_name, _decimal_csv(row.amount)])
    w.writerow(["assets_total", "Assets total", _decimal_csv(report.assets.total)])

    for row in report.liabilities.accounts:
        w.writerow(["liability", row.account_name, _decimal_csv(row.amount)])
    w.writerow(["liabilities_total", "Liabilities total", _decimal_csv(report.liabilities.total)])

    for row in report.equity.accounts:
        key = "equity_computed" if row.is_computed else "equity"
        w.writerow([key, row.account_name, _decimal_csv(row.amount)])
    w.writerow(["equity_total", "Equity total", _decimal_csv(report.equity.total)])

    w.writerow(
        [
            "liabilities_plus_equity",
            "Liabilities + equity",
            _decimal_csv(report.balance_check.liabilities_plus_equity),
        ]
    )
    w.writerow(["is_balanced", "Is balanced", str(report.balance_check.is_balanced).lower()])
    w.writerow(["difference", "Balance", _decimal_csv(report.balance_check.difference)])
    return buf.getvalue().encode("utf-8")


def balance_sheet_report_pdf_bytes(
    report: BalanceSheetReportOut,
    *,
    page_size: PdfPageSizeKind | None = None,
) -> bytes:
    font_path = resolve_pdf_unicode_font_path()
    pdf = create_report_pdf(page_size=page_size)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("ReportFont", "", str(font_path))
    pdf.set_font("ReportFont", size=16)
    pdf.cell(0, 10, text="Balance Sheet", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("ReportFont", size=11)
    pdf.cell(
        0,
        8,
        text=f"As of: {report.period.as_of_date.isoformat()}",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(3)

    def _table(title: str, rows: list[tuple[str, Decimal]], subtotal_label: str, subtotal: Decimal) -> None:
        pdf.set_font("ReportFont", size=12)
        pdf.cell(0, 8, text=title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("ReportFont", size=10)
        pdf.set_fill_color(230, 230, 230)
        pdf.cell(120, 7, text="Account", border=1, fill=True)
        pdf.cell(40, 7, text="Amount", border=1, fill=True, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_fill_color(255, 255, 255)
        for name, amt in rows:
            pdf.cell(120, 7, text=name[:60], border=1)
            pdf.cell(40, 7, text=_format_currency_usd(amt), border=1, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(120, 7, text=f"  {subtotal_label}", border=1)
        pdf.cell(
            40,
            7,
            text=_format_currency_usd(subtotal),
            border=1,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(2)

    _table("Assets", [(r.account_name, r.amount) for r in report.assets.accounts], "Assets total", report.assets.total)
    _table(
        "Liabilities",
        [(r.account_name, r.amount) for r in report.liabilities.accounts],
        "Liabilities total",
        report.liabilities.total,
    )
    _table("Equity", [(r.account_name, r.amount) for r in report.equity.accounts], "Equity total", report.equity.total)

    pdf.ln(4)
    pdf.set_font("ReportFont", size=12)
    pdf.cell(0, 8, text="Balance check", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.set_font("ReportFont", size=11)
    pdf.cell(120, 8, text="Assets total", border=1)
    pdf.cell(
        40,
        8,
        text=_format_currency_usd(report.balance_check.assets_total),
        border=1,
        align="R",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.cell(120, 8, text="Liabilities + equity", border=1)
    pdf.cell(
        40,
        8,
        text=_format_currency_usd(report.balance_check.liabilities_plus_equity),
        border=1,
        align="R",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.cell(120, 8, text="Balance", border=1)
    pdf.cell(
        40,
        8,
        text=_format_currency_usd(report.balance_check.difference),
        border=1,
        align="R",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    out = pdf.output()
    return bytes(out)
