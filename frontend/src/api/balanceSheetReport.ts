import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type BalanceSheetPreset = "today" | "prior_year_end";

export interface BalanceSheetAccountRow {
  account_id: number | null;
  account_name: string;
  account_type: "asset" | "liability" | "equity" | "computed_equity";
  is_active: boolean | null;
  is_computed: boolean;
  amount: string;
}

export interface BalanceSheetSection {
  section: "assets" | "liabilities" | "equity";
  label: string;
  accounts: BalanceSheetAccountRow[];
  total: string;
}

export interface BalanceSheetReport {
  report_schema_version: 1;
  period: { as_of_date: string };
  currency_label: string;
  preset: BalanceSheetPreset | null;
  exclude_requires_review: boolean;
  assets: BalanceSheetSection;
  liabilities: BalanceSheetSection;
  equity: BalanceSheetSection;
  balance_check: {
    assets_total: string;
    liabilities_total: string;
    equity_total: string;
    liabilities_plus_equity: string;
    is_balanced: boolean;
    difference: string;
  };
}

export interface FetchBalanceSheetParams {
  preset?: BalanceSheetPreset;
  presetAnchorDate?: string;
  asOfDate?: string;
  excludeRequiresReview: boolean;
}

function appendBalanceSheetParams(q: URLSearchParams, p: FetchBalanceSheetParams): void {
  q.set("exclude_requires_review", String(p.excludeRequiresReview));
  if (p.preset) {
    q.set("preset", p.preset);
    if (p.presetAnchorDate) {
      q.set("preset_anchor_date", p.presetAnchorDate);
    }
    return;
  }
  if (p.asOfDate) {
    q.set("as_of_date", p.asOfDate);
  }
}

export async function fetchBalanceSheetReport(p: FetchBalanceSheetParams): Promise<BalanceSheetReport> {
  const q = new URLSearchParams();
  appendBalanceSheetParams(q, p);
  const r = await fetch(`${getApiBase()}/reports/balance-sheet?${q}`);
  if (!r.ok) {
    throw new Error(await readApiErrorMessage(r));
  }
  return r.json() as Promise<BalanceSheetReport>;
}

export function balanceSheetExportUrl(format: "csv" | "pdf", p: FetchBalanceSheetParams): string {
  const q = new URLSearchParams();
  q.set("format", format);
  appendBalanceSheetParams(q, p);
  return `${getApiBase()}/reports/balance-sheet/export?${q}`;
}
