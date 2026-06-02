import { getApiBase } from "./baseUrl";
import { ApiHttpError, readApiErrorMessage } from "./errors";

export type BackupExportType = "complete" | "configuration" | "financial";

/** How to handle conflicts for this restore only (sent on import; never part of the archive). */
export type RestoreMode = "abort" | "overwrite" | "erase-reload";

/** Successful restore response fields consumed by the UI (#202). */
export type ImportBackupResult = {
  formatDeprecationWarning?: string;
};

const BACKUP_FILENAME_STEM: Record<BackupExportType, string> = {
  complete: "tallybadger-complete",
  configuration: "tallybadger-config",
  financial: "tallybadger-financial",
};

type FilePickerWindow = Window & {
  showSaveFilePicker?: (options?: SaveFilePickerOptions) => Promise<FileSystemFileHandle>;
};

/** Local-time download name, e.g. `tallybadger-complete-yyyymmdd-hhmmss.tar.gz`. */
export function backupDownloadFilename(exportType: BackupExportType, at: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}${pad(at.getSeconds())}`;
  return `${BACKUP_FILENAME_STEM[exportType]}-${stamp}.tar.gz`;
}

function parseImportBackupResponse(data: unknown): ImportBackupResult {
  const warning =
    typeof data === "object" &&
    data !== null &&
    "format_deprecation_warning" in data &&
    typeof (data as { format_deprecation_warning?: unknown }).format_deprecation_warning === "string"
      ? (data as { format_deprecation_warning: string }).format_deprecation_warning
      : undefined;
  return warning !== undefined ? { formatDeprecationWarning: warning } : {};
}

/** Body for raw gzip import — uses streaming when the runtime supports `File.stream()`. */
function snapshotUploadBody(file: File): BodyInit {
  if (typeof file.stream === "function") {
    return file.stream();
  }
  return file;
}

/** True when the file should use raw-body gzip import (tar.gz), not legacy multipart ZIP. */
export function isTarGzBackupFile(file: File): boolean {
  const name = file.name.toLowerCase();
  if (name.endsWith(".tar.gz") || name.endsWith(".tgz")) {
    return true;
  }
  if (name.endsWith(".zip")) {
    return false;
  }
  if (file.type === "application/gzip" || file.type === "application/x-gzip") {
    return true;
  }
  if (file.type === "application/zip") {
    return false;
  }
  return false;
}

/**
 * Stream export to disk via the File System Access API when available.
 * Falls back to an in-memory blob + programmatic download (Safari, non-secure context).
 */
export async function exportBackupToDisk(exportType: BackupExportType): Promise<void> {
  const params = new URLSearchParams({ export_type: exportType });
  const res = await fetch(`${getApiBase()}/backup/export?${params.toString()}`, { method: "POST" });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await readApiErrorMessage(res));
  }
  if (!res.body) {
    throw new Error("Export response has no body");
  }

  const filename = backupDownloadFilename(exportType);
  const pickerWindow = window as FilePickerWindow;
  if (pickerWindow.showSaveFilePicker) {
    try {
      const handle = await pickerWindow.showSaveFilePicker({
        suggestedName: filename,
        types: [
          {
            description: "Gzip tar archive",
            accept: { "application/gzip": [".tar.gz", ".tgz"] },
          },
        ],
      });
      const writable = await handle.createWritable();
      await res.body.pipeTo(writable);
      return;
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw err;
      }
      // Unsupported or failed picker — fall through to blob download.
    }
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Download a backup archive for the given export scope (loads full archive into memory). */
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
  if (isTarGzBackupFile(file)) {
    const params = new URLSearchParams({ restore_mode: restoreMode });
    const uploadBody = snapshotUploadBody(file);
    const init: RequestInit & { duplex?: "half" } = {
      method: "POST",
      headers: { "Content-Type": "application/gzip" },
      body: uploadBody,
    };
    if (typeof file.stream === "function") {
      init.duplex = "half";
    }
    const res = await fetch(`${getApiBase()}/backup/import?${params.toString()}`, init);
    if (!res.ok) {
      throw new ApiHttpError(res.status, await readApiErrorMessage(res));
    }
    const data: unknown = await res.json();
    return parseImportBackupResponse(data);
  }

  const body = new FormData();
  body.append("snapshot", file);
  body.append("restore_mode", restoreMode);
  const res = await fetch(`${getApiBase()}/backup/import`, { method: "POST", body });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await readApiErrorMessage(res));
  }
  const data: unknown = await res.json();
  return parseImportBackupResponse(data);
}

/** @deprecated Use {@link exportBackup} with `"complete"`. */
export async function exportCompleteBackup(): Promise<Blob> {
  return exportBackup("complete");
}

/** @deprecated Use {@link importBackup}. */
export async function importCompleteBackup(file: File): Promise<void> {
  await importBackup(file, "abort");
}
