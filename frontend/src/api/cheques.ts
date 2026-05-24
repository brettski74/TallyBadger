import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type ChequeStatus = "open" | "cleared" | "void";

export type ChequeListStatus = ChequeStatus | "all";

export type ChequeIncrementUnit = "days" | "weeks" | "months";

export interface Cheque {
  id: number;
  credit_account_id: number;
  debit_account_id: number;
  summary: string;
  cheque_number: number;
  issue_date: string;
  cleared_date: string | null;
  amount: string;
  party_id: number | null;
  status: ChequeStatus;
  created_at: string;
  updated_at: string;
}

export interface ChequeCreateInput {
  credit_account_id: number;
  debit_account_id: number;
  summary: string;
  cheque_number: number;
  issue_date: string;
  amount: string;
  party_id: number | null;
}

export type ChequeUpdateInput = Partial<{
  credit_account_id: number;
  debit_account_id: number;
  summary: string;
  cheque_number: number;
  issue_date: string;
  cleared_date: string | null;
  amount: string;
  party_id: number | null;
  status: ChequeStatus;
}>;

export interface ChequeSeriesScheduleInput {
  increment_unit: ChequeIncrementUnit;
  increment_n: number;
  count?: number;
  end_date?: string;
}

export interface ChequeSeriesCreateInput {
  credit_account_id: number;
  debit_account_id: number;
  summary: string;
  starting_cheque_number: number;
  starting_issue_date: string;
  amount: string;
  party_id: number | null;
  schedule: ChequeSeriesScheduleInput;
}

export interface ChequeSeriesPreviewRow {
  cheque_number: number;
  issue_date: string;
  amount: string;
  number_conflict: boolean;
}

export interface ChequeSeriesPreview {
  rows: ChequeSeriesPreviewRow[];
  series_count: number;
  max_allowed: number;
}

export interface ChequeFilterOption {
  id: number | null;
  name: string;
}

export interface ChequeFilterOptions {
  parties: ChequeFilterOption[];
  credit_accounts: ChequeFilterOption[];
  debit_accounts: ChequeFilterOption[];
}

export interface ChequeListParams {
  status?: ChequeListStatus;
  party_ids?: (number | null)[];
  credit_account_ids?: number[];
  debit_account_ids?: number[];
  issue_from_date?: string;
  issue_to_date?: string;
  cleared_from_date?: string;
  cleared_to_date?: string;
  min_amount?: string;
  max_amount?: string;
  summary?: string;
}

function appendIdList(search: URLSearchParams, key: string, ids: number[] | undefined): void {
  if (!ids?.length) {
    return;
  }
  for (const id of ids) {
    search.append(key, String(id));
  }
}

function appendPartyIdList(search: URLSearchParams, ids: (number | null)[] | undefined): void {
  if (!ids?.length) {
    return;
  }
  for (const id of ids) {
    search.append("party_ids", id === null ? "null" : String(id));
  }
}

export async function listCheques(params: ChequeListParams = {}): Promise<Cheque[]> {
  const search = new URLSearchParams();
  if (params.status !== undefined) {
    search.set("status", params.status);
  }
  appendPartyIdList(search, params.party_ids);
  appendIdList(search, "credit_account_ids", params.credit_account_ids);
  appendIdList(search, "debit_account_ids", params.debit_account_ids);
  if (params.issue_from_date) {
    search.set("issue_from_date", params.issue_from_date);
  }
  if (params.issue_to_date) {
    search.set("issue_to_date", params.issue_to_date);
  }
  if (params.cleared_from_date) {
    search.set("cleared_from_date", params.cleared_from_date);
  }
  if (params.cleared_to_date) {
    search.set("cleared_to_date", params.cleared_to_date);
  }
  if (params.min_amount?.trim()) {
    search.set("min_amount", params.min_amount.trim());
  }
  if (params.max_amount?.trim()) {
    search.set("max_amount", params.max_amount.trim());
  }
  if (params.summary?.trim()) {
    search.set("summary", params.summary.trim());
  }
  const query = search.toString();
  const response = await fetch(`${getApiBase()}/cheques${query ? `?${query}` : ""}`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  const body = (await response.json()) as { cheques: Cheque[] };
  return body.cheques;
}

export async function listChequeFilterOptions(): Promise<ChequeFilterOptions> {
  const response = await fetch(`${getApiBase()}/cheques/filter-options`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function getCheque(chequeId: number): Promise<Cheque> {
  const response = await fetch(`${getApiBase()}/cheques/${chequeId}`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function createCheque(payload: ChequeCreateInput): Promise<Cheque> {
  const response = await fetch(`${getApiBase()}/cheques`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...payload,
      cleared_date: null,
    }),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function previewChequeSeries(payload: ChequeSeriesCreateInput): Promise<ChequeSeriesPreview> {
  const response = await fetch(`${getApiBase()}/cheques/series/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function createChequeSeries(payload: ChequeSeriesCreateInput): Promise<Cheque[]> {
  const response = await fetch(`${getApiBase()}/cheques/series`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function patchCheque(chequeId: number, patch: ChequeUpdateInput): Promise<Cheque> {
  const response = await fetch(`${getApiBase()}/cheques/${chequeId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}
