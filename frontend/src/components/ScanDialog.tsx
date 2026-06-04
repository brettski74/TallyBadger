import { useEffect, useMemo, useRef, useState } from "react";
import { FileScan } from "lucide-react";

import type { Account } from "../api/accounts";
import type { AccrualDirection } from "../api/accrualPlans";
import type { Party } from "../api/parties";

export interface ScanDialogJournalParams {
  summary: string;
  externalReference: string | null;
}

export interface ScanDialogAccrualParams extends ScanDialogJournalParams {
  partyId: number;
  targetAccountId: number;
  amount: string;
  billDate: string;
  dueDate: string | null;
  direction: AccrualDirection;
}

type ScanDialogBaseProps = {
  open: boolean;
  title?: string;
  subtitle?: string;
  partyBlockedReason?: string | null;
  onDismiss: () => void;
};

type ScanDialogJournalProps = ScanDialogBaseProps & {
  mode: "journal-entry";
  onScan: (params: ScanDialogJournalParams) => Promise<void>;
};

type ScanDialogAccrualProps = ScanDialogBaseProps & {
  mode: "accrual";
  parties: Party[];
  accounts: Account[];
  onScan: (params: ScanDialogAccrualParams) => Promise<void>;
};

export type ScanDialogProps = ScanDialogJournalProps | ScanDialogAccrualProps;

export function ScanDialog(props: ScanDialogProps) {
  const {
    open,
    title = "Scan from flatbed",
    subtitle,
    partyBlockedReason = null,
    onDismiss,
    mode,
  } = props;
  const dialogRef = useRef<HTMLDialogElement>(null);
  const summaryRef = useRef<HTMLInputElement>(null);
  const [summary, setSummary] = useState("");
  const [externalReference, setExternalReference] = useState("");
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [direction, setDirection] = useState<AccrualDirection>("expense");
  const [partyId, setPartyId] = useState("");
  const [targetAccountId, setTargetAccountId] = useState("");
  const [amount, setAmount] = useState("");
  const [billDate, setBillDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [dueDate, setDueDate] = useState("");

  const accrualParties = mode === "accrual" ? props.parties.filter((p) => p.is_active) : [];
  const targetAccountOptions = useMemo(() => {
    if (mode !== "accrual") {
      return [];
    }
    return props.accounts.filter((a) =>
      direction === "revenue" ? a.type === "revenue" : a.type === "expense",
    );
  }, [mode, props, direction]);

  useEffect(() => {
    if (mode !== "accrual") {
      return;
    }
    if (!targetAccountOptions.some((a) => String(a.id) === targetAccountId)) {
      setTargetAccountId("");
    }
  }, [mode, targetAccountOptions, targetAccountId]);

  useEffect(() => {
    const el = dialogRef.current;
    if (!open) {
      el?.close();
      setSummary("");
      setExternalReference("");
      setError(null);
      setScanning(false);
      setDirection("expense");
      setPartyId("");
      setTargetAccountId("");
      setAmount("");
      setBillDate(new Date().toISOString().slice(0, 10));
      setDueDate("");
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

  function validateAccrualFields(): string | null {
    if (mode !== "accrual") {
      return null;
    }
    if (!partyId) {
      return "Party is required.";
    }
    if (!targetAccountId) {
      return "Target account is required.";
    }
    const amountTrim = amount.trim();
    if (!amountTrim) {
      return "Amount is required.";
    }
    const parsed = Number(amountTrim);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return "Amount must be a positive number.";
    }
    if (!billDate) {
      return "Bill date is required.";
    }
    return null;
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
    const accrualError = validateAccrualFields();
    if (accrualError) {
      setError(accrualError);
      return;
    }
    setScanning(true);
    setError(null);
    try {
      const base = {
        summary: summaryClean,
        externalReference: externalReference.trim() === "" ? null : externalReference.trim(),
      };
      if (mode === "journal-entry") {
        await props.onScan(base);
      } else {
        await props.onScan({
          ...base,
          partyId: Number(partyId),
          targetAccountId: Number(targetAccountId),
          amount: amount.trim(),
          billDate,
          dueDate: dueDate.trim() === "" ? null : dueDate.trim(),
          direction,
        });
      }
      onDismiss();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  }

  const submitLabel = mode === "accrual" ? "Scan and create accrual" : "Scan and attach";

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
          <div className="cheque-form-grid">
            {mode === "accrual" && (
              <>
                <div className="cheque-form-col">
                  <label>
                    Party (required)
                    <select
                      aria-label="Bill party"
                      value={partyId}
                      onChange={(e) => setPartyId(e.target.value)}
                      disabled={scanning || Boolean(partyBlockedReason)}
                      required
                    >
                      <option value="">Select party</option>
                      {accrualParties.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Target account (required)
                    <select
                      aria-label="Accrual target account"
                      value={targetAccountId}
                      onChange={(e) => setTargetAccountId(e.target.value)}
                      disabled={scanning || Boolean(partyBlockedReason)}
                      required
                    >
                      <option value="">Select target account</option>
                      {targetAccountOptions.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Direction
                    <select
                      aria-label="Accrual direction"
                      value={direction}
                      onChange={(e) => setDirection(e.target.value as AccrualDirection)}
                      disabled={scanning || Boolean(partyBlockedReason)}
                    >
                      <option value="expense">expense</option>
                      <option value="revenue">revenue</option>
                    </select>
                  </label>
                </div>
                <div className="cheque-form-col">
                  <label>
                    Bill date (required)
                    <input
                      aria-label="Bill date"
                      type="date"
                      value={billDate}
                      onChange={(e) => setBillDate(e.target.value)}
                      disabled={scanning || Boolean(partyBlockedReason)}
                      required
                    />
                  </label>
                  <label>
                    Due date (optional)
                    <input
                      aria-label="Due date"
                      type="date"
                      value={dueDate}
                      onChange={(e) => setDueDate(e.target.value)}
                      disabled={scanning || Boolean(partyBlockedReason)}
                    />
                  </label>
                  <label>
                    Amount (required)
                    <input
                      aria-label="Bill amount"
                      type="text"
                      inputMode="decimal"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      disabled={scanning || Boolean(partyBlockedReason)}
                      required
                    />
                  </label>
                </div>
              </>
            )}
            <label className="cheque-form-summary">
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
            <label className="cheque-form-summary">
              External reference (optional)
              <input
                aria-label="External reference"
                value={externalReference}
                onChange={(e) => setExternalReference(e.target.value)}
                maxLength={500}
                disabled={scanning || Boolean(partyBlockedReason)}
              />
            </label>
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={scanning || Boolean(partyBlockedReason)}>
            {scanning ? "Scanning…" : submitLabel}
          </button>
        </form>
      </div>
    </dialog>
  );
}
