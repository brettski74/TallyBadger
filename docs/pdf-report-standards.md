# PDF financial report standards

Normative layout and rendering rules for **server-generated PDF exports** of financial reports (Income & Expense, Balance Sheet, Account Statement, and future tabular reports). CSV export shapes are defined per report; this document covers **PDF only**.

**Reference implementation:** [`src/tallybadger/api/account_statement_export.py`](../src/tallybadger/api/account_statement_export.py) (account statement, landscape tabular layout). Older exporters ([`income_expense_export.py`](../src/tallybadger/api/income_expense_export.py), [`balance_sheet_export.py`](../src/tallybadger/api/balance_sheet_export.py)) use simpler two-column tables and predate some of these rules; **new tabular reports** and substantive revisions to existing PDFs should follow this document.

## Shared infrastructure

| Concern | Location | Rule |
|---------|----------|------|
| Page size | [`ledger_settings.pdf_page_size`](../src/tallybadger/ledger/models.py) (`us-letter` \| `a4`) | Read from `LedgerService.get_ledger_settings()` at **export** time (Configuration tab). Default **`us-letter`**. Do not use environment variables for page size. |
| `FPDF` construction | [`src/tallybadger/api/pdf_page.py`](../src/tallybadger/api/pdf_page.py) | Use `create_report_pdf(orientation=…, page_size=…)`. Portrait for section-style reports; landscape when a wide multi-column table is the primary content (account statement). |
| Unicode font | [`resolve_pdf_unicode_font_path()`](../src/tallybadger/api/income_expense_export.py) | Register as `ReportFont` on each document. Override path with `TALLYBADGER_PDF_FONT_PATH` only when the host lacks DejaVu. |
| USD display in PDF | `_format_currency_usd()` in [`income_expense_export.py`](../src/tallybadger/api/income_expense_export.py) | `$` prefix, thousands grouping, two decimals — match on-screen report preview. |

## Page layout

- **Units:** millimetres (`unit="mm"`).
- **Margins:** `10` mm left, top, and right unless a report documents a deliberate exception.
- **Table width:** span the full **effective page width** (`pdf.epw` — width between left and right margins). Do not use fixed column widths that leave a large unused margin on one side.
- **Cell padding:** set `pdf.c_margin` to `1.0` mm for tabular reports (minimal horizontal inset inside cells).
- **Title block:** report name at 16 pt; period or as-of line at 11 pt; small gap before the table.

## Typography (tabular reports)

| Element | Font size (pt) |
|---------|----------------|
| Body / data cells | 8 |
| Column headers | 9 |
| Title | 16 |
| Subtitle (period, as-of) | 11 |

Use the active font size when measuring string widths for column sizing.

## Cell borders and row rules

Match the web register border colour **`#e2e8f0`** (RGB **226, 232, 240** — frontend `--border`).

- **No vertical rules** between columns. Do not draw full cell frames (`border=1` on every side).
- **Horizontal rules only:** one light line under each data row and under the header row.
- **Line weight:** `0.15` mm.
- **Draw method:** `pdf.set_draw_color(226, 232, 240)`, `pdf.set_line_width(0.15)`, then `pdf.line(x, y, x + table_width, y)` at the bottom edge of the row.

Section-style reports (revenue/expense account lists) may retain filled header rows until migrated; prefer horizontal rules when touching those exporters.

## Vertical alignment

All columns in a row share one **row height**. Text is **vertically centred** within that height.

1. **Measure** wrapped text height per cell (`multi_cell` with `dry_run=True`, `output=HEIGHT`).
2. **Row height** = max of minimum row height (`7` mm) and the tallest wrapped text column in that row (single-line columns do not drive height unless they are the only content).
3. **Single-line columns** (dates, currency amounts): `cell()` at the row origin with the full row height — fpdf centres single-line text vertically in the cell box.
4. **Wrapping columns** (summary, names, labels): compute `content_h`, set `y_text = y + (row_height - content_h) / 2`, then `multi_cell` at `(x, y_text)` with `border=0`.

Apply the same rules to **header** cells.

## Text wrapping

- **Wrap** free-text columns with `multi_cell` and word wrap (`WrapMode.WORD`).
- **Do not truncate** with arbitrary `[:N]` slices; export content should match on-screen data.
- **Single-line columns** must be wide enough that wrapping never occurs in normal data (see column width rules below). Use `cell()`, not `multi_cell`, for those columns.

## Column width algorithm (multi-column tables)

Use a **two-tier** model: **fixed** columns sized from content, then **variable** columns sharing the remainder.

### 1. Fixed columns

**Date (ISO `yyyy-mm-dd`):**

- Measure at body font size for every date in the report plus a ceiling sample (`2099-12-31`).
- Measure the header label at header font size (`Entry date` or equivalent).
- Column width = max measured width + horizontal cell padding (`2 × c_margin`).
- Fixed width for the whole document; never shrink below this.

**Currency (debit, credit, balance, amount, etc.):**

- One shared width for all money columns in the row (or one width per column if labels differ materially — account statement uses one width for Debit, Credit, Balance).
- Floor amount: **`max(largest |amount| in report, $100,000.00)`** — format the larger value with `_format_currency_usd` and measure at body font size.
- Also measure header labels at header font size.
- Width = max measured + horizontal padding.
- Render with right alignment (`align="R"`).

### 2. Variable text columns

Remaining width = `epw − fixed_date − n × fixed_money` (and any other fixed columns).

For each variable column, compute **average character count per row** over the report body (string length of the cell value; empty → 0). Use those averages as **weights** to split `remaining_width`.

**Minimum width:** `10` ems per variable column, where **em** = `pdf.get_string_width("0")` at the body font size.

**Allocation loop:**

1. Distribute `remaining_width` among free columns in proportion to their weights (equal weights if all averages are zero).
2. If any column would be narrower than `10` ems, **pin** it at `10` ems, subtract from `remaining_width`, remove it from the pool, and repeat with the remaining columns.
3. If `remaining_width < 30` ems total (less than three minimums), **split evenly** in thirds instead of weighting.

**Edge case:** if fixed columns alone exceed `epw`, scale fixed columns down to 65% of `epw` collectively, then allocate text columns from what is left (rare on landscape Letter/A4).

### 3. Horizontal alignment

| Column kind | Alignment |
|-------------|-----------|
| Dates, labels, narrative text | Left (`L`) |
| Money | Right (`R`) |

## Pagination (wide tables)

Account statement pattern:

- `set_auto_page_break(auto=False)`; manually check space before each row.
- On overflow: `add_page()`, redraw **column headers only** (not the title block).
- After redrawing headers, reset the active font to **body size** before drawing data rows (header drawing leaves the larger header font active).
- Reserve a **bottom margin** (~15 mm) before breaking.

Portrait section reports may use `auto_page_break=True` with a bottom margin until migrated to the manual pattern.

## Filenames and HTTP

- Follow existing report exporters: `Content-Disposition` attachment, stem includes report kind and salient parameters (account name, dates).
- PDF export routes pass `page_size` from `service.get_ledger_settings().pdf_page_size` into `*_pdf_bytes(report, page_size=…)`.

## Tests

When adding or changing PDF layout logic:

- **Unit:** pure helpers (e.g. text-column width allocation) without rendering; PDF bytes smoke tests with `pypdf` text extraction where stable.
- **Integration:** export endpoint returns `application/pdf` and key labels/amounts appear in extracted text.
- Changing shared constants (border colour, min em count, money floor) should update this document in the same PR.

## Consistency with the web UI

PDF tables should **mirror on-screen columns and row semantics** (same headers, same special rows such as balance forward / closing balance, same USD formatting). Styling is allowed to differ (horizontal rules vs full grid), but **data and column meaning** must align.
