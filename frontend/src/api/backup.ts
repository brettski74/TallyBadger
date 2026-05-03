import { getApiBase } from "./baseUrl";
import { ApiHttpError, readApiErrorMessage } from "./errors";

/** Download a complete backup ZIP (`export_type: complete`). */
export async function exportCompleteBackup(): Promise<Blob> {
  const res = await fetch(`${getApiBase()}/backup/export`, { method: "POST" });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await readApiErrorMessage(res));
  }
  return res.blob();
}

/** Restore a complete backup into an **empty** database (409 if data exists). */
export async function importCompleteBackup(file: File): Promise<void> {
  const body = new FormData();
  body.append("snapshot", file);
  const res = await fetch(`${getApiBase()}/backup/import`, { method: "POST", body });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await readApiErrorMessage(res));
  }
}
