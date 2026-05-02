import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export interface LedgerSettings {
  accounts_receivable_account_id: number | null;
  accounts_payable_account_id: number | null;
  unearned_revenue_account_id: number | null;
  unallocated_debits_account_id: number | null;
  unallocated_credits_account_id: number | null;
  updated_at: string;
}

export interface Obligation {
  id: number;
  party_id: number;
  source_entry_id: number | null;
  source_entry_date: string | null;
  source_entry_summary: string | null;
  obligation_type: "receivable" | "payable" | "unearned";
  status: "open" | "partially_settled" | "settled" | "reconciled";
  original_amount: string;
  open_amount: string;
}

export interface SettlementAllocation {
  obligation_id: number;
  amount: string;
}

export interface SettlementPayload {
  party_id: number;
  settlement_type: "receipt" | "payment";
  event_date: string;
  amount: string;
  cash_account_id: number;
  allocations: SettlementAllocation[];
  note: string | null;
}

export async function getLedgerSettings(): Promise<LedgerSettings> {
  const response = await fetch(`${getApiBase()}/ledger-settings`);
  if (!response.ok) throw new Error(await readApiErrorMessage(response));
  return response.json();
}

export async function updateLedgerSettings(payload: Partial<LedgerSettings>): Promise<LedgerSettings> {
  const response = await fetch(`${getApiBase()}/ledger-settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readApiErrorMessage(response));
  return response.json();
}

export async function listOpenObligations(partyId: number): Promise<Obligation[]> {
  const response = await fetch(`${getApiBase()}/obligations/${partyId}`);
  if (!response.ok) throw new Error(await readApiErrorMessage(response));
  return response.json();
}

export async function createSettlement(payload: SettlementPayload) {
  const response = await fetch(`${getApiBase()}/settlements`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readApiErrorMessage(response));
  return response.json();
}
