import { FormEvent, useEffect, useRef, useState } from "react";

import type { Account } from "../api/accounts";
import {
  fetchAccountStatementReport,
  type AccountStatementReport,
  type FetchAccountStatementParams,
} from "../api/accountStatementReport";
import { priorCompletedCalendarMonthRange } from "../lib/priorCompletedCalendarMonth";

export interface AccountStatementSettingsDialogProps {
  open: boolean;
  account: Account | null;
  onDismiss: () => void;
  onReportLoaded: (report: AccountStatementReport, params: FetchAccountStatementParams) => void;
}

export function AccountStatementSettingsDialog({
  open,
  account,
  onDismiss,
  onReportLoaded,
}: AccountStatementSettingsDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const defaults = priorCompletedCalendarMonthRange();
  const [startDate, setStartDate] = useState(defaults.startDate);
  const [endDate, setEndDate] = useState(defaults.endDate);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = dialogRef.current;
    if (!open || !account) {
      el?.close();
      setError(null);
      setLoading(false);
      return;
    }
    const range = priorCompletedCalendarMonthRange();
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    el?.showModal();
  }, [open, account]);

  async function handleRun(event: FormEvent) {
    event.preventDefault();
    if (!account) {
      return;
    }
    setError(null);
    setLoading(true);
    const params: FetchAccountStatementParams = {
      accountId: account.id,
      startDate,
      endDate,
    };
    try {
      const report = await fetchAccountStatementReport(params);
      onReportLoaded(report, params);
      dialogRef.current?.close();
      onDismiss();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load account statement");
    } finally {
      setLoading(false);
    }
  }

  if (!account) {
    return null;
  }

  return (
    <dialog
      ref={dialogRef}
      className="cheque-dialog account-statement-settings-dialog"
      aria-labelledby="account-statement-settings-title"
      onClose={onDismiss}
      onCancel={(e) => {
        e.preventDefault();
        onDismiss();
      }}
    >
      <div className="cheque-dialog-inner">
        <div className="cheque-dialog-header">
          <h2 id="account-statement-settings-title">Account statement</h2>
          <button type="button" className="button-secondary" onClick={onDismiss}>
            Close
          </button>
        </div>
        <form onSubmit={(e) => void handleRun(e)}>
          <div className="cheque-form-grid">
            <div className="cheque-form-col">
              <label htmlFor="stmt-account-name">Account</label>
              <input id="stmt-account-name" type="text" readOnly value={account.name} />
            </div>
            <div className="cheque-form-col">
              <label htmlFor="stmt-start-date">Start date</label>
              <input
                id="stmt-start-date"
                type="date"
                required
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="cheque-form-col">
              <label htmlFor="stmt-end-date">End date</label>
              <input
                id="stmt-end-date"
                type="date"
                required
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>
          <div className="dialog-actions">
            <button type="button" className="button-secondary" onClick={onDismiss}>
              Cancel
            </button>
            <button type="submit" disabled={loading}>
              {loading ? "Loading…" : "Run"}
            </button>
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </form>
      </div>
    </dialog>
  );
}
