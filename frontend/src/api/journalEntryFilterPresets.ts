import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";
import type { ChequeAssociation } from "./journalEntries";

export interface JournalEntryFilterPresetSortKey {
  field: string;
  direction: "asc" | "desc";
}

export interface JournalEntryFilterPresetDefinition {
  from_date?: string | null;
  to_date?: string | null;
  needs_review?: boolean | null;
  account_ids?: number[];
  party_ids?: number[];
  accrual_plan_ids?: number[];
  amount_low?: number | null;
  amount_high?: number | null;
  cheque_association?: ChequeAssociation;
  /** CSV import file basename (matches journal list filter; #136). */
  import_basename?: string | null;
  sort?: JournalEntryFilterPresetSortKey[];
}

export interface JournalEntryFilterPreset {
  id: number;
  name: string;
  definition: JournalEntryFilterPresetDefinition;
  created_at: string;
  updated_at: string;
}

export interface JournalEntryFilterPresetWriteInput {
  name: string;
  definition: JournalEntryFilterPresetDefinition;
}

export async function listJournalEntryFilterPresets(): Promise<JournalEntryFilterPreset[]> {
  const response = await fetch(`${getApiBase()}/journal-entry-filter-presets`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function createJournalEntryFilterPreset(
  payload: JournalEntryFilterPresetWriteInput,
): Promise<JournalEntryFilterPreset> {
  const response = await fetch(`${getApiBase()}/journal-entry-filter-presets`, {
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

export async function updateJournalEntryFilterPreset(
  presetId: number,
  payload: JournalEntryFilterPresetWriteInput,
): Promise<JournalEntryFilterPreset> {
  const response = await fetch(
    `${getApiBase()}/journal-entry-filter-presets/${presetId}`,
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

export async function deleteJournalEntryFilterPreset(presetId: number): Promise<void> {
  const response = await fetch(
    `${getApiBase()}/journal-entry-filter-presets/${presetId}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
}
