import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export interface JournalLineOut {
  id: number;
  account_id: number;
  party_id?: number | null;
  account_name: string;
  party_name?: string | null;
  amount: string;
  settlement_allocation_id?: number | null;
  obligation_id?: number | null;
}

export interface JournalEntrySettlementAllocationOut {
  id: number;
  obligation_id: number;
  amount: string;
}

export interface JournalEntryReviewMessage {
  id: number;
  message: string;
  created_at: string;
}

export interface JournalEntryOut {
  id: number;
  entry_date: string;
  summary: string;
  description: string | null;
  requires_review: boolean;
  cheque_id: number | null;
  created_at: string;
  updated_at: string;
  lines: JournalLineOut[];
  review_messages: JournalEntryReviewMessage[];
  settlement_allocations?: JournalEntrySettlementAllocationOut[];
  accrual_plan_id?: number | null;
  accrual_plan_name?: string | null;
}

export interface JournalEntryListItem {
  id: number;
  entry_date: string;
  summary: string;
  description: string | null;
  requires_review: boolean;
  cheque_id: number | null;
  created_at: string;
  updated_at: string;
  debit_side_label: string;
  credit_side_label: string;
  party_labels: string;
  amount: string;
}

export interface JournalLineIn {
  account_id: number;
  party_id?: number | null;
  amount: string;
  obligation_id?: number | null;
}

export interface SettlementPreviewAllocationOut {
  obligation_id: number;
  accrual_date: string | null;
  source_entry_summary: string | null;
  open_amount: string;
  applied_amount: string;
  settlement_type: "receipt" | "payment";
}

export interface JournalEntrySettlementPreviewOut {
  party_id: number;
  party_name: string;
  lines: JournalLineIn[];
  allocations: SettlementPreviewAllocationOut[];
  receipt_cash_amount: string | null;
  payment_cash_amount: string | null;
}

export interface JournalEntryWrite {
  entry_date: string;
  summary: string;
  description: string | null;
  lines: JournalLineIn[];
  requires_review?: boolean;
  review_messages?: string[];
  cheque_id?: number | null;
}

export type ChequeAssociation = "any" | "with_cheque" | "without_cheque";

export interface ListJournalEntriesParams {
  from_date?: string;
  to_date?: string;
  needs_review?: boolean;
  account_ids?: number[];
  party_ids?: number[];
  accrual_plan_ids?: number[];
  amount_low?: number;
  amount_high?: number;
  cheque_association?: ChequeAssociation;
  /** Filter entries whose import batch basename matches (case-insensitive). */
  import_basename?: string;
  sort?: string[];
  limit?: number;
  offset?: number;
}

export async function listJournalEntries(
  params: ListJournalEntriesParams = {},
): Promise<JournalEntryListItem[]> {
  const base = getApiBase();
  const search = new URLSearchParams();
  if (params.from_date) {
    search.set("from_date", params.from_date);
  }
  if (params.to_date) {
    search.set("to_date", params.to_date);
  }
  if (params.needs_review === true) {
    search.set("needs_review", "true");
  }
  for (const id of params.account_ids ?? []) {
    search.append("account_ids", String(id));
  }
  for (const id of params.party_ids ?? []) {
    search.append("party_ids", String(id));
  }
  for (const id of params.accrual_plan_ids ?? []) {
    search.append("accrual_plan_ids", String(id));
  }
  if (params.amount_low != null) {
    search.set("amount_low", String(params.amount_low));
  }
  if (params.amount_high != null) {
    search.set("amount_high", String(params.amount_high));
  }
  if (params.cheque_association && params.cheque_association !== "any") {
    search.set("cheque_association", params.cheque_association);
  }
  if (params.import_basename != null && params.import_basename.trim() !== "") {
    search.set("import_basename", params.import_basename.trim());
  }
  for (const token of params.sort ?? []) {
    search.append("sort", token);
  }
  if (params.limit != null) {
    search.set("limit", String(params.limit));
  }
  if (params.offset != null) {
    search.set("offset", String(params.offset));
  }
  const query = search.toString();
  const url = query ? `${base}/journal-entries?${query}` : `${base}/journal-entries`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function getJournalEntry(entryId: number): Promise<JournalEntryOut> {
  const response = await fetch(`${getApiBase()}/journal-entries/${entryId}`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function previewJournalEntrySettlement(
  payload: JournalEntryWrite,
): Promise<JournalEntrySettlementPreviewOut | null> {
  const response = await fetch(`${getApiBase()}/journal-entries/settlement-preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  const data: unknown = await response.json();
  if (data == null) {
    return null;
  }
  return data as JournalEntrySettlementPreviewOut;
}

export async function createJournalEntry(payload: JournalEntryWrite): Promise<JournalEntryOut> {
  const response = await fetch(`${getApiBase()}/journal-entries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function updateJournalEntry(
  entryId: number,
  payload: JournalEntryWrite,
): Promise<JournalEntryOut> {
  const response = await fetch(`${getApiBase()}/journal-entries/${entryId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function deleteJournalEntryReviewMessage(
  entryId: number,
  messageId: number,
): Promise<void> {
  const response = await fetch(
    `${getApiBase()}/journal-entries/${entryId}/review-messages/${messageId}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
}
