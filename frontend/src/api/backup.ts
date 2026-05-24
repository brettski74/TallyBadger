import { getApiBase } from "./baseUrl";
import { ApiHttpError, readApiErrorMessage } from "./errors";

export type BackupExportType = "complete" | "configuration" | "financial";

/** How to handle conflicts for this restore only (sent on import; never part of the ZIP). */
export type RestoreMode = "abort" | "overwrite" | "erase_reload";

/** Successful restore response fields consumed by the UI (#202). */
export type ImportBackupResult = {
  formatDeprecationWarning?: string;
};

const BACKUP_FILENAME_STEM: Record<BackupExportType, string> = {
  complete: "tallybadger-complete",
  configuration: "tallybadger-config",
  financial: "tallybadger-financial",
};

/** Local-time download name, e.g. `tallybadger-complete-yyyymmdd-hhmmss.zip`. */
export function backupDownloadFilename(exportType: BackupExportType, at: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}${pad(at.getSeconds())}`;
  return `${BACKUP_FILENAME_STEM[exportType]}-${stamp}.zip`;
}

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
export async function importBackup(
  file: File,
  restoreMode: RestoreMode = "abort",
): Promise<ImportBackupResult> {
  const body = new FormData();
  body.append("snapshot", file);
  body.append("restore_mode", restoreMode);
  const res = await fetch(`${getApiBase()}/backup/import`, { method: "POST", body });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await readApiErrorMessage(res));
  }
  const data: unknown = await res.json();
  const warning =
    typeof data === "object" &&
    data !== null &&
    "format_deprecation_warning" in data &&
    typeof (data as { format_deprecation_warning?: unknown }).format_deprecation_warning === "string"
      ? (data as { format_deprecation_warning: string }).format_deprecation_warning
      : undefined;
  return warning !== undefined ? { formatDeprecationWarning: warning } : {};
}

/** @deprecated Use {@link exportBackup} with `"complete"`. */
export async function exportCompleteBackup(): Promise<Blob> {
  return exportBackup("complete");
}

/** @deprecated Use {@link importBackup}. */
export async function importCompleteBackup(file: File): Promise<void> {
  return importBackup(file, "abort");
}
