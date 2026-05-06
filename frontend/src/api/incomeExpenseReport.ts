import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type IncomeExpensePreset = "current_year_to_date" | "prior_full_year" | "prior_year_to_date";

export interface IncomeExpenseAccountRow {
  account_id: number;
  account_name: string;
  account_type: "revenue" | "expense";
  is_active: boolean;
  amount: string;
}

export interface IncomeExpenseReport {
  report_schema_version: 1;
  period: { start_date: string; end_date: string };
  currency_label: string;
  preset: IncomeExpensePreset | null;
  exclude_zero_balance_accounts: boolean;
  revenue_accounts: IncomeExpenseAccountRow[];
  expense_accounts: IncomeExpenseAccountRow[];
  total_revenue: string;
  total_expense: string;
  net_income: string;
}

export interface FetchIncomeExpenseParams {
  preset?: IncomeExpensePreset;
  /** ISO date (YYYY-MM-DD); used with preset as the anchor for YTD-style ranges (browser local calendar day). */
  asOfDate?: string;
  startDate?: string;
  endDate?: string;
  excludeZeroBalanceAccounts: boolean;
}

function appendIncomeExpenseParams(q: URLSearchParams, p: FetchIncomeExpenseParams): void {
  q.set("exclude_zero_balance_accounts", String(p.excludeZeroBalanceAccounts));
  if (p.preset) {
    q.set("preset", p.preset);
    if (p.asOfDate) {
      q.set("as_of_date", p.asOfDate);
    }
  } else {
    if (p.startDate) {
      q.set("start_date", p.startDate);
    }
    if (p.endDate) {
      q.set("end_date", p.endDate);
    }
  }
}

export async function fetchIncomeExpenseReport(p: FetchIncomeExpenseParams): Promise<IncomeExpenseReport> {
  const q = new URLSearchParams();
  appendIncomeExpenseParams(q, p);
  const r = await fetch(`${getApiBase()}/reports/income-expense?${q}`);
  if (!r.ok) {
    throw new Error(await readApiErrorMessage(r));
  }
  return r.json() as Promise<IncomeExpenseReport>;
}

/** Same query as ``fetchIncomeExpenseReport`` plus ``format`` for download URLs (GET). */
export function incomeExpenseExportUrl(format: "csv" | "pdf", p: FetchIncomeExpenseParams): string {
  const q = new URLSearchParams();
  q.set("format", format);
  appendIncomeExpenseParams(q, p);
  return `${getApiBase()}/reports/income-expense/export?${q}`;
}
