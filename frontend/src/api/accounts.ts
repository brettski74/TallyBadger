import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type AccountType = "asset" | "liability" | "equity" | "revenue" | "expense";

export interface Account {
  id: number;
  name: string;
  type: AccountType;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateAccountInput {
  name: string;
  type: AccountType;
  is_active: boolean;
}

export async function listAccounts(): Promise<Account[]> {
  const response = await fetch(`${getApiBase()}/accounts`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function createAccount(payload: CreateAccountInput): Promise<Account> {
  const response = await fetch(`${getApiBase()}/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }

  return response.json();
}
