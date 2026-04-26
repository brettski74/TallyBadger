import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type PartyRole = "customer" | "vendor" | "both" | "other";

export interface Party {
  id: number;
  name: string;
  role: PartyRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PartyCreateInput {
  name: string;
  role: PartyRole;
  is_active: boolean;
}

export interface PartyUpdateInput {
  name?: string;
  role?: PartyRole;
  is_active?: boolean;
}

export async function listParties(): Promise<Party[]> {
  const response = await fetch(`${getApiBase()}/parties`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function createParty(payload: PartyCreateInput): Promise<Party> {
  const response = await fetch(`${getApiBase()}/parties`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
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
  return response.json();
}
