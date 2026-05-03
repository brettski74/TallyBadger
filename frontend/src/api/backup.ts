import { getApiBase } from "./baseUrl";
import { ApiHttpError, readApiErrorMessage } from "./errors";

export type BackupExportType = "complete" | "configuration" | "financial";
export type DuplicateImportPolicy = "abort" | "overwrite";

/** Download a backup ZIP for the given export scope. */
export async function exportBackup(exportType: BackupExportType): Promise<Blob> {
  const params = new URLSearchParams({ export_type: exportType });
  const res = await fetch(`${getApiBase()}/backup/export?${params.toString()}`, { method: "POST" });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await readApiErrorMessage(res));
  }
  return res.blob();
}

/** Import a snapshot; default duplicate policy requires empty tables in the snapshot scope. */
export async function importBackup(
  file: File,
  duplicatePolicy: DuplicateImportPolicy = "abort",
): Promise<void> {
  const body = new FormData();
  body.append("snapshot", file);
  body.append("duplicate_policy", duplicatePolicy);
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
