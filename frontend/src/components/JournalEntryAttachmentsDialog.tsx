import { useCallback, useEffect, useRef, useState } from "react";
import { FileScan } from "lucide-react";

import { getJournalEntry } from "../api/journalEntries";
import {
  attachmentMimeSupportsInlinePreview,
  attachmentUploadLimitMessage,
  fetchJournalEntryAttachmentBlob,
  isAttachmentOverUploadLimit,
  listJournalEntryAttachments,
  scanJournalEntryAttachment,
  unlinkJournalEntryAttachment,
  uploadJournalEntryAttachment,
  type JournalEntryAttachmentOut,
} from "../api/journalEntryAttachments";
import { getLedgerSettings } from "../api/settlements";
import { ScanDialog } from "./ScanDialog";

const UNLINK_CONFIRM =
  "Remove this attachment from the journal entry? The file may be deleted from storage if nothing else references it.";

function isPdfMime(mimeType: string): boolean {
  return (mimeType.toLowerCase().split(";")[0]?.trim() ?? "") === "application/pdf";
}

export interface JournalEntryAttachmentsDialogProps {
  entryId: number | null;
  onDismiss: () => void;
}

export function JournalEntryAttachmentsDialog({ entryId, onDismiss }: JournalEntryAttachmentsDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [items, setItems] = useState<JournalEntryAttachmentOut[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(false);

  const [uploadSummary, setUploadSummary] = useState("");
  const [uploadExternalRef, setUploadExternalRef] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [maxUploadBytes, setMaxUploadBytes] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [scanOpen, setScanOpen] = useState(false);
  const [entrySubtitle, setEntrySubtitle] = useState<string | null>(null);

  const [preview, setPreview] = useState<{
    attachment: JournalEntryAttachmentOut;
    url: string;
  } | null>(null);
  const previewRef = useRef(preview);
  previewRef.current = preview;
  const [previewLoadingId, setPreviewLoadingId] = useState<number | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const revokePreview = useCallback(() => {
    setPreview((prev) => {
      if (prev?.url) {
        URL.revokeObjectURL(prev.url);
      }
      return null;
    });
    setPreviewError(null);
    setPreviewLoadingId(null);
  }, []);

  const loadList = useCallback(async (id: number) => {
    setListLoading(true);
    setListError(null);
    try {
      const rows = await listJournalEntryAttachments(id);
      setItems(rows);
    } catch (err) {
      setItems(null);
      setListError(err instanceof Error ? err.message : "Failed to load attachments");
    } finally {
      setListLoading(false);
    }
  }, []);

  const loadEntryContext = useCallback(async (id: number) => {
    try {
      const entry = await getJournalEntry(id);
      setEntrySubtitle(`Journal entry #${id} · ${entry.entry_date} · ${entry.summary}`);
    } catch (err) {
      setEntrySubtitle(`Journal entry #${id}`);
    }
  }, []);

  useEffect(() => {
    const el = dialogRef.current;
    if (entryId == null) {
      el?.close();
      revokePreview();
      setItems(null);
      setListError(null);
      setUploadSummary("");
      setUploadExternalRef("");
      setUploadFile(null);
      setMaxUploadBytes(null);
      setUploadError(null);
      setScanOpen(false);
      setEntrySubtitle(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }
    el?.showModal();
    void loadList(entryId);
    void loadEntryContext(entryId);
    void getLedgerSettings()
      .then((settings) => setMaxUploadBytes(settings.max_attachment_upload_bytes))
      .catch(() => setMaxUploadBytes(null));
  }, [entryId, loadEntryContext, loadList, revokePreview]);

  function handleDialogClose() {
    revokePreview();
    onDismiss();
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (entryId == null || !uploadFile) {
      return;
    }
    const summary = uploadSummary.trim();
    if (!summary) {
      setUploadError("Summary is required.");
      return;
    }
    if (maxUploadBytes == null) {
      setUploadError("Upload limit not loaded yet — try again in a moment.");
      return;
    }
    if (isAttachmentOverUploadLimit(uploadFile.size, maxUploadBytes)) {
      setUploadError(attachmentUploadLimitMessage(maxUploadBytes));
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      await uploadJournalEntryAttachment(entryId, {
        file: uploadFile,
        summary,
        externalReference: uploadExternalRef.trim() === "" ? null : uploadExternalRef.trim(),
        maxUploadBytes,
      });
      setUploadSummary("");
      setUploadExternalRef("");
      setUploadFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await loadList(entryId);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleScan(params: { summary: string; externalReference: string | null }) {
    if (entryId == null) {
      return;
    }
    await scanJournalEntryAttachment(entryId, params);
    await loadList(entryId);
  }

  async function handleDownload(att: JournalEntryAttachmentOut) {
    if (entryId == null) {
      return;
    }
    try {
      const { blob } = await fetchJournalEntryAttachmentBlob(entryId, att.id);
      const name = att.original_filename?.trim() || `attachment-${att.id}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Download failed");
    }
  }

  async function handleView(att: JournalEntryAttachmentOut) {
    if (entryId == null || !attachmentMimeSupportsInlinePreview(att.mime_type)) {
      return;
    }
    revokePreview();
    setPreviewLoadingId(att.id);
    setPreviewError(null);
    try {
      const { blob } = await fetchJournalEntryAttachmentBlob(entryId, att.id);
      const url = URL.createObjectURL(blob);
      setPreview({ attachment: att, url });
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "Could not load preview");
    } finally {
      setPreviewLoadingId(null);
    }
  }

  function handleRemoveClick(att: JournalEntryAttachmentOut) {
    if (entryId == null) {
      return;
    }
    if (!window.confirm(UNLINK_CONFIRM)) {
      return;
    }
    void (async () => {
      try {
        await unlinkJournalEntryAttachment(entryId, att.id);
        revokePreview();
        await loadList(entryId);
      } catch (err) {
        setListError(err instanceof Error ? err.message : "Remove failed");
      }
    })();
  }

  if (entryId == null) {
    return null;
  }

  return (
    <>
      <ScanDialog
        open={scanOpen}
        subtitle={entrySubtitle ?? undefined}
        onDismiss={() => setScanOpen(false)}
        onScan={handleScan}
      />
      <dialog
        ref={dialogRef}
        className={preview ? "attachments-dialog attachments-dialog-preview-open" : "attachments-dialog"}
        onClose={handleDialogClose}
        onCancel={(e) => {
          e.preventDefault();
          if (previewRef.current) {
            revokePreview();
            return;
          }
          dialogRef.current?.close();
        }}
      >
        {preview ? (
          <div
            className="attachments-preview-fullscreen"
            role="document"
            aria-label={`Preview: ${preview.attachment.summary}`}
          >
            <header className="attachments-preview-fullscreen-bar">
              <p className="attachments-preview-fullscreen-title" title={preview.attachment.summary}>
                {preview.attachment.summary}
              </p>
              <button
                type="button"
                className="attachments-preview-close-x"
                onClick={revokePreview}
                aria-label="Close preview"
              >
                <svg
                  className="attachments-preview-close-x-icon"
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  aria-hidden
                  focusable="false"
                >
                  <path
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    d="M18 6L6 18M6 6l12 12"
                  />
                </svg>
              </button>
            </header>
            <div className="attachments-preview-fullscreen-body">
              {isPdfMime(preview.attachment.mime_type) ? (
                <iframe
                  className="attachments-preview-fullscreen-iframe"
                  title={`Preview ${preview.attachment.summary}`}
                  src={preview.url}
                />
              ) : (
                <img
                  className="attachments-preview-fullscreen-img"
                  src={preview.url}
                  alt={preview.attachment.summary}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="attachments-dialog-inner">
            <div className="attachments-dialog-header">
              <h2 id="attachments-dialog-title">Attachments</h2>
              <button type="button" className="button-secondary" onClick={() => dialogRef.current?.close()}>
                Close
              </button>
            </div>
            <p className="muted attachments-dialog-subtitle">Journal entry #{entryId}</p>

            {previewError && (
              <p className="error" role="alert">
                {previewError}
              </p>
            )}

            <div className="attachments-add-actions">
              <h3 className="attachments-section-title">Add attachment</h3>
              <button
                type="button"
                className="button-secondary attachments-scan-button"
                onClick={() => setScanOpen(true)}
                disabled={uploading}
                aria-label="Scan from flatbed"
              >
                <FileScan aria-hidden size={18} />
                Scan
              </button>
            </div>

            <form className="attachments-upload-form" onSubmit={(e) => void handleUpload(e)}>
              <h3 className="attachments-section-title">Upload</h3>
              <label>
                File
                <input
                  ref={fileInputRef}
                  type="file"
                  onChange={(e) => {
                    const file = e.target.files?.[0] ?? null;
                    setUploadFile(file);
                    if (file && maxUploadBytes != null && isAttachmentOverUploadLimit(file.size, maxUploadBytes)) {
                      setUploadError(attachmentUploadLimitMessage(maxUploadBytes));
                    } else {
                      setUploadError(null);
                    }
                  }}
                  disabled={uploading}
                />
              </label>
              <label>
                Summary (required)
                <input
                  aria-label="Attachment summary"
                  value={uploadSummary}
                  onChange={(e) => setUploadSummary(e.target.value)}
                  maxLength={500}
                  disabled={uploading}
                />
              </label>
              <label>
                External reference (optional)
                <input
                  aria-label="External reference"
                  value={uploadExternalRef}
                  onChange={(e) => setUploadExternalRef(e.target.value)}
                  maxLength={500}
                  disabled={uploading}
                />
              </label>
              {uploadError && (
                <p className="error" role="alert">
                  {uploadError}
                </p>
              )}
              <button
                type="submit"
                disabled={
                  uploading ||
                  !uploadFile ||
                  maxUploadBytes == null ||
                  isAttachmentOverUploadLimit(uploadFile.size, maxUploadBytes)
                }
              >
                {uploading ? "Uploading…" : "Upload"}
              </button>
            </form>

            <h3 className="attachments-section-title">Attached files</h3>
            {listLoading && items === null && <p>Loading…</p>}
            {listError && (
              <p className="error" role="alert">
                {listError}
              </p>
            )}
            {!listLoading && items && items.length === 0 && !listError && (
              <p className="muted">No attachments yet.</p>
            )}
            {items && items.length > 0 && (
              <table className="attachments-table">
                <thead>
                  <tr>
                    <th>Summary</th>
                    <th>File / type</th>
                    <th aria-label="actions" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((att) => (
                    <tr key={att.id}>
                      <td>{att.summary}</td>
                      <td>
                        <span className="attachments-meta">
                          {att.original_filename ?? "—"}
                          <span className="muted"> · {att.mime_type}</span>
                        </span>
                        {att.external_reference && (
                          <span className="muted attachments-external-ref">Ref: {att.external_reference}</span>
                        )}
                      </td>
                      <td>
                        <div className="attachments-row-actions">
                          <button type="button" className="button-link" onClick={() => void handleDownload(att)}>
                            Download
                          </button>
                          {attachmentMimeSupportsInlinePreview(att.mime_type) && (
                            <button
                              type="button"
                              className="button-link"
                              disabled={previewLoadingId === att.id}
                              onClick={() => void handleView(att)}
                            >
                              {previewLoadingId === att.id ? "Loading…" : "View"}
                            </button>
                          )}
                          <button type="button" className="button-link" onClick={() => handleRemoveClick(att)}>
                            Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </dialog>
    </>
  );
}
