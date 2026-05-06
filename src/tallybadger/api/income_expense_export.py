"""CSV and PDF serialization for the Income & Expense report."""

from __future__ import annotations

import csv
import io
import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from tallybadger.ledger.models import IncomeExpenseReportOut


def _decimal_csv(d: Decimal) -> str:
    """Fixed-point decimal string for CSV (period as separator, no thousands grouping)."""
    return format(d, "f")


def _format_currency_usd(d: Decimal) -> str:
    """Display currency for PDF (matches on-screen preview: $, grouping, two decimals)."""
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if q < 0:
        return f"-${format(abs(q), ',.2f')}"
    return f"${format(q, ',.2f')}"


def resolve_pdf_unicode_font_path() -> Path:
    """Locate a TTF for PDF output (DejaVu or similar)."""
    env = os.environ.get("TALLYBADGER_PDF_FONT_PATH")
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
        raise RuntimeError(f"TALLYBADGER_PDF_FONT_PATH is not a file: {env}")
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise RuntimeError(
        "No Unicode TTF found for PDF export; install fonts-dejavu-core (Debian/Ubuntu) "
        "or ttf-dejavu (Arch), or set TALLYBADGER_PDF_FONT_PATH to DejaVuSans.ttf",
    )


def income_expense_report_filename_stem(report: IncomeExpenseReportOut) -> str:
    s = report.period.start_date.isoformat()
    e = report.period.end_date.isoformat()
    return f"income-expense_{s}_{e}"


def income_expense_report_csv_bytes(report: IncomeExpenseReportOut) -> bytes:
    """UTF-8 CSV: metadata, then revenue lines, revenue subtotal, expense lines, expense subtotal, net income.

    Columns: ``field``, ``value``, ``amount``. Account rows use ``field`` = ``revenue`` or ``expense``,
    ``value`` = account name. Section closers: ``revenue_subtotal``, ``expense_subtotal``, ``net_income``
    with human labels in ``value`` and amounts in ``amount``. Uses UTF-8 and ``.`` as decimal separator
    (no thousands grouping in CSV amounts).
    """
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["field", "value", "amount"])
    w.writerow(["report", "income_expense", ""])
    w.writerow(["period_start", report.period.start_date.isoformat(), ""])
    w.writerow(["period_end", report.period.end_date.isoformat(), ""])
    w.writerow(["exclude_zero_balance_accounts", str(report.exclude_zero_balance_accounts).lower(), ""])
    if report.preset:
        w.writerow(["preset", report.preset, ""])
    for row in report.revenue_accounts:
        w.writerow(["revenue", row.account_name, _decimal_csv(row.amount)])
    w.writerow(["revenue_subtotal", "Revenue subtotal", _decimal_csv(report.total_revenue)])
    for row in report.expense_accounts:
        w.writerow(["expense", row.account_name, _decimal_csv(row.amount)])
    w.writerow(["expense_subtotal", "Expense subtotal", _decimal_csv(report.total_expense)])
    w.writerow(["net_income", "Net income", _decimal_csv(report.net_income)])
    return buf.getvalue().encode("utf-8")


def income_expense_report_pdf_bytes(report: IncomeExpenseReportOut) -> bytes:
    """PDF mirroring on-screen layout: per-account lines, section subtotals, net income last."""

    font_path = resolve_pdf_unicode_font_path()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("ReportFont", "", str(font_path))
    pdf.set_font("ReportFont", size=16)
    pdf.cell(0, 10, text="Income & Expense", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("ReportFont", size=11)
    pdf.cell(
        0,
        8,
        text=f"Period: {report.period.start_date.isoformat()} – {report.period.end_date.isoformat()}",
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

    _table(
        "Revenue accounts",
        [(r.account_name, r.amount) for r in report.revenue_accounts],
        "Revenue subtotal",
        report.total_revenue,
    )
    _table(
        "Expense accounts",
        [(r.account_name, r.amount) for r in report.expense_accounts],
        "Expense subtotal",
        report.total_expense,
    )

    pdf.set_font("ReportFont", size=11)
    pdf.cell(120, 8, text="Net income", border=1)
    pdf.cell(
        40,
        8,
        text=_format_currency_usd(report.net_income),
        border=1,
        align="R",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    out = pdf.output()
    return bytes(out)
