import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export interface JournalLineOut {
  id: number;
  account_id: number;
  party_id?: number | null;
  account_name: string;
  party_name?: string | null;
  amount: string;
}

export interface JournalEntryOut {
  id: number;
  entry_date: string;
  summary: string;
  description: string | null;
  requires_review: boolean;
  created_at: string;
  updated_at: string;
  lines: JournalLineOut[];
}

export interface JournalEntryListItem {
  id: number;
  entry_date: string;
  summary: string;
  description: string | null;
  requires_review: boolean;
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
}

export interface JournalEntryWrite {
  entry_date: string;
  summary: string;
  description: string | null;
  lines: JournalLineIn[];
  requires_review?: boolean;
}

export interface ListJournalEntriesParams {
  from_date?: string;
  to_date?: string;
  needs_review?: boolean;
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
