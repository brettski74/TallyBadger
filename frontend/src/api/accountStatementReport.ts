import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type AccountStatementRowKind = "balance_forward" | "activity" | "closing_balance";

export interface AccountStatementRow {
  row_kind: AccountStatementRowKind;
  entry_date: string;
  summary: string;
  counterparty_account: string | null;
  party: string | null;
  debit: string | null;
  credit: string | null;
  balance: string;
  entry_id: number | null;
}

export interface AccountStatementReport {
  report_schema_version: 1;
  account: { account_id: number; account_name: string; is_active: boolean };
  period: { start_date: string; end_date: string };
  currency_label: string;
  balance_forward: string;
  closing_balance: string;
  rows: AccountStatementRow[];
}

export interface FetchAccountStatementParams {
  accountId: number;
  startDate: string;
  endDate: string;
}

function appendAccountStatementParams(q: URLSearchParams, p: FetchAccountStatementParams): void {
  q.set("account_id", String(p.accountId));
  q.set("start_date", p.startDate);
  q.set("end_date", p.endDate);
}

export async function fetchAccountStatementReport(
  p: FetchAccountStatementParams,
): Promise<AccountStatementReport> {
  const q = new URLSearchParams();
  appendAccountStatementParams(q, p);
  const r = await fetch(`${getApiBase()}/reports/account-statement?${q}`);
  if (!r.ok) {
    throw new Error(await readApiErrorMessage(r));
  }
  return r.json() as Promise<AccountStatementReport>;
}

export function accountStatementExportUrl(
  format: "csv" | "pdf",
  p: FetchAccountStatementParams,
): string {
  const q = new URLSearchParams();
  q.set("format", format);
  appendAccountStatementParams(q, p);
  return `${getApiBase()}/reports/account-statement/export?${q}`;
}
