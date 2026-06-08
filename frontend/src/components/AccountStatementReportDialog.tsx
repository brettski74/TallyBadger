import { useEffect, useRef } from "react";

import {
  accountStatementExportUrl,
  type AccountStatementReport,
  type AccountStatementRow,
  type FetchAccountStatementParams,
} from "../api/accountStatementReport";

function formatReportCurrency(amountStr: string | null): string {
  if (amountStr == null || amountStr === "") {
    return "";
  }
  const n = Number(amountStr);
  if (!Number.isFinite(n)) {
    return amountStr;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

function rowKey(row: AccountStatementRow, index: number): string {
  if (row.entry_id != null) {
    return `entry-${row.entry_id}`;
  }
  return `${row.row_kind}-${index}`;
}

export interface AccountStatementReportDialogProps {
  open: boolean;
  report: AccountStatementReport | null;
  params: FetchAccountStatementParams | null;
  onDismiss: () => void;
}

export function AccountStatementReportDialog({
  open,
  report,
  params,
  onDismiss,
}: AccountStatementReportDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = dialogRef.current;
    if (!open || !report) {
      el?.close();
      return;
    }
    el?.showModal();
  }, [open, report]);

  if (!report || !params) {
    return null;
  }

  return (
    <dialog
      ref={dialogRef}
      className="cheque-dialog account-statement-report-dialog"
      aria-labelledby="account-statement-report-title"
      onClose={onDismiss}
      onCancel={(e) => {
        e.preventDefault();
        onDismiss();
      }}
    >
      <div className="account-statement-report-shell">
        <div className="account-statement-report-chrome">
          <div className="cheque-dialog-header account-statement-report-header">
            <div>
              <h2 id="account-statement-report-title">{report.account.account_name} Statement</h2>
              <p className="account-statement-report-period muted">
                <span>Start Date: {report.period.start_date}</span>
                <span>End Date: {report.period.end_date}</span>
              </p>
            </div>
            <button type="button" className="button-secondary" onClick={onDismiss}>
              Close
            </button>
          </div>
        </div>

        <div className="account-statement-report-scroll" tabIndex={0}>
          <table className="journal-entry-list account-statement-report-table">
            <thead>
              <tr>
                <th scope="col">Entry date</th>
                <th scope="col">Summary</th>
                <th scope="col">Account</th>
                <th scope="col">Party</th>
                <th className="journal-list-amount" scope="col">
                  Debit
                </th>
                <th className="journal-list-amount" scope="col">
                  Credit
                </th>
                <th className="journal-list-amount" scope="col">
                  Balance
                </th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row, index) => (
                <tr key={rowKey(row, index)} className={`account-statement-row-${row.row_kind}`}>
                  <td>{row.entry_date}</td>
                  <td>{row.summary}</td>
                  <td>{row.counterparty_account ?? ""}</td>
                  <td>{row.party ?? ""}</td>
                  <td className="journal-list-amount">{formatReportCurrency(row.debit)}</td>
                  <td className="journal-list-amount">{formatReportCurrency(row.credit)}</td>
                  <td className="journal-list-amount">{formatReportCurrency(row.balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="account-statement-report-footer form-actions-inline">
          <a
            className="button-secondary"
            href={accountStatementExportUrl("csv", params)}
            download
          >
            Export CSV
          </a>
          <a
            className="button-secondary"
            href={accountStatementExportUrl("pdf", params)}
            download
          >
            Export PDF
          </a>
        </div>
      </div>
    </dialog>
  );
}
