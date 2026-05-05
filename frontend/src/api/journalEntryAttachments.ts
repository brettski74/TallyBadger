import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export interface JournalEntryAttachmentOut {
  id: number;
  summary: string;
  external_reference: string | null;
  mime_type: string;
  original_filename: string | null;
  created_at: string;
  updated_at: string;
}

export function attachmentMimeSupportsInlinePreview(mimeType: string): boolean {
  const base = mimeType.toLowerCase().split(";")[0]?.trim() ?? "";
  return (
    base === "image/jpeg" ||
    base === "image/jpg" ||
    base === "image/png" ||
    base === "application/pdf"
  );
}

export async function listJournalEntryAttachments(
  entryId: number,
): Promise<JournalEntryAttachmentOut[]> {
  const response = await fetch(`${getApiBase()}/journal-entries/${entryId}/attachments`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export interface UploadJournalEntryAttachmentParams {
  file: File;
  summary: string;
  externalReference?: string | null;
}

export async function uploadJournalEntryAttachment(
  entryId: number,
  params: UploadJournalEntryAttachmentParams,
): Promise<JournalEntryAttachmentOut> {
  const body = new FormData();
  body.append("file", params.file);
  body.append("summary", params.summary);
  const ext = params.externalReference?.trim();
  if (ext) {
    body.append("external_reference", ext);
  }
  const response = await fetch(`${getApiBase()}/journal-entries/${entryId}/attachments`, {
    method: "POST",
    body,
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function fetchJournalEntryAttachmentBlob(
  entryId: number,
  attachmentId: number,
): Promise<{ blob: Blob; contentType: string | null }> {
  const response = await fetch(
    `${getApiBase()}/journal-entries/${entryId}/attachments/${attachmentId}`,
  );
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  const blob = await response.blob();
  return { blob, contentType: response.headers.get("Content-Type") };
}

export async function unlinkJournalEntryAttachment(entryId: number, attachmentId: number): Promise<void> {
  const response = await fetch(
    `${getApiBase()}/journal-entries/${entryId}/attachments/${attachmentId}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
}
