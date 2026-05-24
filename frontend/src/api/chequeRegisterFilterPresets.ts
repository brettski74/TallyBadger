import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";
import type { ChequeListStatus } from "./cheques";

export interface ChequeRegisterFilterPresetSortKey {
  field: string;
  direction: "asc" | "desc";
}

export type ChequeRegisterPartyFilterId = number | "null";

export interface ChequeRegisterFilterPresetDefinition {
  status?: ChequeListStatus | null;
  party_ids?: ChequeRegisterPartyFilterId[];
  credit_account_ids?: number[];
  debit_account_ids?: number[];
  issue_from_date?: string | null;
  issue_to_date?: string | null;
  cleared_from_date?: string | null;
  cleared_to_date?: string | null;
  min_amount?: string | null;
  max_amount?: string | null;
  summary?: string | null;
  sort?: ChequeRegisterFilterPresetSortKey[];
}

export interface ChequeRegisterFilterPreset {
  id: number;
  name: string;
  definition: ChequeRegisterFilterPresetDefinition;
  created_at: string;
  updated_at: string;
}

export interface ChequeRegisterFilterPresetWriteInput {
  name: string;
  definition: ChequeRegisterFilterPresetDefinition;
}

export async function listChequeRegisterFilterPresets(): Promise<ChequeRegisterFilterPreset[]> {
  const response = await fetch(`${getApiBase()}/cheque-register-filter-presets`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function createChequeRegisterFilterPreset(
  payload: ChequeRegisterFilterPresetWriteInput,
): Promise<ChequeRegisterFilterPreset> {
  const response = await fetch(`${getApiBase()}/cheque-register-filter-presets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const err = new Error(await readApiErrorMessage(response)) as Error & {
      status?: number;
    };
    err.status = response.status;
    throw err;
  }
  return response.json();
}

export async function updateChequeRegisterFilterPreset(
  presetId: number,
  payload: ChequeRegisterFilterPresetWriteInput,
): Promise<ChequeRegisterFilterPreset> {
  const response = await fetch(
    `${getApiBase()}/cheque-register-filter-presets/${presetId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function deleteChequeRegisterFilterPreset(presetId: number): Promise<void> {
  const response = await fetch(
    `${getApiBase()}/cheque-register-filter-presets/${presetId}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
}
