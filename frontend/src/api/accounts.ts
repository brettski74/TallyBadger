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

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8080";

export async function listAccounts(): Promise<Account[]> {
  const response = await fetch(`${API_BASE}/accounts`);
  if (!response.ok) {
    throw new Error("Failed to load accounts");
  }
  return response.json();
}

export async function createAccount(payload: CreateAccountInput): Promise<Account> {
  const response = await fetch(`${API_BASE}/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (response.status === 409) {
    const data = await response.json();
    throw new Error(data.detail ?? "Account already exists");
  }

  if (!response.ok) {
    throw new Error("Failed to create account");
  }

  return response.json();
}
