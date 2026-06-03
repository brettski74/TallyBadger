import { useEffect, useRef, useState } from "react";
import { FileScan } from "lucide-react";

export interface ScanDialogProps {
  open: boolean;
  title?: string;
  subtitle?: string;
  partyBlockedReason?: string | null;
  onDismiss: () => void;
  onScan: (params: { summary: string; externalReference: string | null }) => Promise<void>;
}

export function ScanDialog({
  open,
  title = "Scan from flatbed",
  subtitle,
  partyBlockedReason = null,
  onDismiss,
  onScan,
}: ScanDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const summaryRef = useRef<HTMLInputElement>(null);
  const [summary, setSummary] = useState("");
  const [externalReference, setExternalReference] = useState("");
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = dialogRef.current;
    if (!open) {
      el?.close();
      setSummary("");
      setExternalReference("");
      setError(null);
      setScanning(false);
      return;
    }
    el?.showModal();
    summaryRef.current?.focus();
  }, [open]);

  function handleClose() {
    if (scanning) {
      return;
    }
    onDismiss();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (partyBlockedReason) {
      return;
    }
    const summaryClean = summary.trim();
    if (!summaryClean) {
      setError("Summary is required.");
      return;
    }
    setScanning(true);
    setError(null);
    try {
      await onScan({
        summary: summaryClean,
        externalReference: externalReference.trim() === "" ? null : externalReference.trim(),
      });
      onDismiss();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="attachments-dialog scan-dialog"
      aria-labelledby="scan-dialog-title"
      onClose={handleClose}
    >
      <div className="attachments-dialog-inner">
        <div className="attachments-dialog-header">
          <h2 id="scan-dialog-title">
            <FileScan className="scan-dialog-title-icon" aria-hidden size={20} />
            {title}
          </h2>
          <button
            type="button"
            className="button-secondary"
            onClick={handleClose}
            disabled={scanning}
          >
            Cancel
          </button>
        </div>
        {subtitle && <p className="muted attachments-dialog-subtitle">{subtitle}</p>}
        {partyBlockedReason && (
          <p className="error" role="alert">
            {partyBlockedReason}
          </p>
        )}
        <form className="attachments-upload-form" onSubmit={(e) => void handleSubmit(e)}>
          <p className="muted">
            Place a single page on the flatbed. The server captures a greyscale JPEG at 300 dpi (US
            Letter scan area).
          </p>
          <label>
            Summary (required)
            <input
              ref={summaryRef}
              aria-label="Scan summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              maxLength={200}
              disabled={scanning || Boolean(partyBlockedReason)}
            />
          </label>
          <label>
            External reference (optional)
            <input
              aria-label="External reference"
              value={externalReference}
              onChange={(e) => setExternalReference(e.target.value)}
              maxLength={500}
              disabled={scanning || Boolean(partyBlockedReason)}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={scanning || Boolean(partyBlockedReason)}>
            {scanning ? "Scanning…" : "Scan and attach"}
          </button>
        </form>
      </div>
    </dialog>
  );
}
