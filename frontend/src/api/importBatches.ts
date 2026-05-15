import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export interface ImportBatchListItem {
  id: number;
  basename: string;
  loaded_at: string;
  is_active: boolean;
}

export async function listImportBatches(limit = 200): Promise<ImportBatchListItem[]> {
  const search = new URLSearchParams();
  if (limit !== 200) {
    search.set("limit", String(limit));
  }
  const q = search.toString();
  const url = q ? `${getApiBase()}/import-batches?${q}` : `${getApiBase()}/import-batches`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}
