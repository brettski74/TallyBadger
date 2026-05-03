import { getApiBase } from "./baseUrl";
import { ApiHttpError, readApiErrorMessage } from "./errors";

export type BackupExportType = "complete" | "configuration" | "financial";

/** How to handle conflicts for this restore only (sent on import; never part of the ZIP). */
export type RestoreMode = "abort" | "overwrite" | "erase_reload";

/** Download a backup ZIP for the given export scope. */
export async function exportBackup(exportType: BackupExportType): Promise<Blob> {
  const params = new URLSearchParams({ export_type: exportType });
  const res = await fetch(`${getApiBase()}/backup/export?${params.toString()}`, { method: "POST" });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await readApiErrorMessage(res));
  }
  return res.blob();
}

/** Import a snapshot using the chosen restore behaviour for this request only. */
export async function importBackup(file: File, restoreMode: RestoreMode = "abort"): Promise<void> {
  const body = new FormData();
  body.append("snapshot", file);
  body.append("restore_mode", restoreMode);
  const res = await fetch(`${getApiBase()}/backup/import`, { method: "POST", body });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await readApiErrorMessage(res));
  }
}

/** @deprecated Use {@link exportBackup} with `"complete"`. */
export async function exportCompleteBackup(): Promise<Blob> {
  return exportBackup("complete");
}

/** @deprecated Use {@link importBackup}. */
export async function importCompleteBackup(file: File): Promise<void> {
  return importBackup(file, "abort");
}
