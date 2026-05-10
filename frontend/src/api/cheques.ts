import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type ChequeStatus = "open" | "cleared" | "void";

export type ChequeListStatus = ChequeStatus | "all";

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

export async function listCheques(params: { status?: ChequeListStatus } = {}): Promise<Cheque[]> {
  const search = new URLSearchParams();
  search.set("status", params.status ?? "open");
  const response = await fetch(`${getApiBase()}/cheques?${search.toString()}`);
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
