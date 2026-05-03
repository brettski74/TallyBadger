import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type PartyRole = "customer" | "vendor" | "both" | "other";

export interface Party {
  id: number;
  name: string;
  role: PartyRole;
  is_active: boolean;
  subtype?: string | null;
  match_patterns: string[];
  default_revenue_account_id?: number | null;
  default_expense_account_id?: number | null;
  default_revenue_account_name?: string | null;
  default_expense_account_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PartyCreateInput {
  name: string;
  role: PartyRole;
  is_active: boolean;
  subtype?: string | null;
  match_patterns?: string[];
  default_revenue_account_id?: number | null;
  default_expense_account_id?: number | null;
}

export interface PartyUpdateInput {
  name?: string;
  role?: PartyRole;
  is_active?: boolean;
  subtype?: string | null;
  match_patterns?: string[];
  default_revenue_account_id?: number | null;
  default_expense_account_id?: number | null;
}

export async function listParties(): Promise<Party[]> {
  const response = await fetch(`${getApiBase()}/parties`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  const data: unknown = await response.json();
  if (!Array.isArray(data)) {
    return [];
  }
  return data.map((row) => normalizeParty(row as Record<string, unknown>));
}

function normalizeParty(row: Record<string, unknown>): Party {
  const mp = row.match_patterns;
  const patterns = Array.isArray(mp) ? mp.map((x) => String(x)) : [];
  return {
    id: Number(row.id),
    name: String(row.name),
    role: row.role as PartyRole,
    is_active: Boolean(row.is_active),
    subtype: row.subtype == null ? null : String(row.subtype),
    match_patterns: patterns,
    default_revenue_account_id:
      row.default_revenue_account_id == null ? null : Number(row.default_revenue_account_id),
    default_expense_account_id:
      row.default_expense_account_id == null ? null : Number(row.default_expense_account_id),
    default_revenue_account_name:
      row.default_revenue_account_name == null ? null : String(row.default_revenue_account_name),
    default_expense_account_name:
      row.default_expense_account_name == null ? null : String(row.default_expense_account_name),
    created_at: String(row.created_at),
    updated_at: String(row.updated_at),
  };
}

export async function listPartySubtypeSuggestions(): Promise<string[]> {
  const response = await fetch(`${getApiBase()}/parties/subtype-suggestions`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  const data: unknown = await response.json();
  if (!Array.isArray(data)) {
    return [];
  }
  return data.map((x) => String(x));
}

export async function createParty(payload: PartyCreateInput): Promise<Party> {
  const response = await fetch(`${getApiBase()}/parties`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...payload,
      match_patterns: payload.match_patterns ?? [],
    }),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return normalizeParty((await response.json()) as Record<string, unknown>);
}

export async function updateParty(partyId: number, payload: PartyUpdateInput): Promise<Party> {
  const response = await fetch(`${getApiBase()}/parties/${partyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return normalizeParty((await response.json()) as Record<string, unknown>);
}
