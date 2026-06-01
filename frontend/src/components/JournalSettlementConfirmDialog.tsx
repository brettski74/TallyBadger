import { useEffect, useMemo, useRef } from "react";

import type { Account } from "../api/accounts";
import type {
  JournalEntrySettlementPreviewOut,
  JournalLineIn,
} from "../api/journalEntries";
import type { Party } from "../api/parties";

export interface JournalSettlementConfirmDialogProps {
  open: boolean;
  preview: JournalEntrySettlementPreviewOut | null;
  originalPayload: { entry_date: string; lines: JournalLineIn[] } | null;
  accounts: Account[];
  parties: Party[];
  saving: boolean;
  error: string | null;
  onAccept: () => void | Promise<void>;
  onDecline: () => void | Promise<void>;
  onCancel: () => void;
}

function accountName(accounts: Account[], accountId: number): string {
  return accounts.find((a) => a.id === accountId)?.name ?? `Account #${accountId}`;
}

function partyName(parties: Party[], partyId: number | null | undefined): string {
  if (partyId == null) {
    return "—";
  }
  return parties.find((p) => p.id === partyId)?.name ?? `Party #${partyId}`;
}

function formatProposedLine(
  line: JournalLineIn,
  accounts: Account[],
  parties: Party[],
  obligationSummaryById: Map<number, string | null>,
): { account: string; party: string; amount: string; obligation: string } {
  const obligationSummary =
    line.obligation_id != null
      ? (obligationSummaryById.get(line.obligation_id) ?? null)
      : null;
  return {
    account: accountName(accounts, line.account_id),
    party: partyName(parties, line.party_id),
    amount: line.amount,
    obligation: obligationSummary ?? "—",
  };
}

export function JournalSettlementConfirmDialog({
  open,
  preview,
  originalPayload,
  accounts,
  parties,
  saving,
  error,
  onAccept,
  onDecline,
  onCancel,
}: JournalSettlementConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = dialogRef.current;
    if (!el) {
      return;
    }
    if (open && !el.open) {
      el.showModal();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open]);

  const obligationSummaryById = useMemo(() => {
    const map = new Map<number, string | null>();
    if (preview) {
      for (const allocation of preview.allocations) {
        map.set(allocation.obligation_id, allocation.source_entry_summary);
      }
    }
    return map;
  }, [preview]);

  const displayLines = useMemo(() => {
    if (!preview) {
      return [];
    }
    if (!originalPayload) {
      return preview.lines;
    }
    if (originalPayload.lines.length !== 2 || preview.lines.length !== 2 || preview.allocations.length !== 1) {
      return preview.lines;
    }
    const allocation = preview.allocations[0];
    if (allocation.accrual_date == null || allocation.accrual_date !== originalPayload.entry_date) {
      return preview.lines;
    }
    if (Number(allocation.applied_amount) !== Number(allocation.open_amount)) {
      return preview.lines;
    }
    const cashAmount =
      allocation.settlement_type === "payment"
        ? preview.payment_cash_amount
        : preview.receipt_cash_amount;
    if (cashAmount == null || Number(cashAmount) !== Number(allocation.applied_amount)) {
      return preview.lines;
    }
    const obligationLines = preview.lines.filter((line) => line.obligation_id != null);
    if (obligationLines.length !== 1) {
      return preview.lines;
    }
    // For same-day full settlement collapse, posting keeps the original P/L+cash shape.
    return originalPayload.lines.map((line) => ({ ...line, obligation_id: null }));
  }, [preview, originalPayload]);

  const showsCollapsedOutcome =
    preview != null &&
    originalPayload != null &&
    displayLines.length === originalPayload.lines.length &&
    preview.lines.some((line) => line.obligation_id != null) &&
    displayLines.every((line) => line.obligation_id == null);

  const proposedRows = useMemo(
    () =>
      preview
        ? displayLines.map((line) => formatProposedLine(line, accounts, parties, obligationSummaryById))
        : [],
    [preview, displayLines, accounts, parties, obligationSummaryById],
  );

  if (preview == null) {
    return null;
  }

  return (
    <dialog
      ref={dialogRef}
      className="journal-settlement-confirm-dialog"
      aria-label="Confirm obligation settlement"
      onClose={onCancel}
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
    >
      <div className="journal-settlement-confirm-inner">
        <h2>Settle open obligations?</h2>
        <p>
          Open obligations exist for <strong>{preview.party_name}</strong>. You can post with automatic
          settlement allocations or keep the entry as entered (no allocations).
        </p>

        <h3>Settlement breakdown</h3>
        <table className="journal-entry-list" aria-label="Settlement allocations">
          <thead>
            <tr>
              <th>Obligation</th>
              <th>Accrual date</th>
              <th>Open amount</th>
              <th>Applied amount</th>
            </tr>
          </thead>
          <tbody>
            {preview.allocations.map((row) => (
              <tr key={row.obligation_id}>
                <td>{row.source_entry_summary ?? "—"}</td>
                <td>{row.accrual_date ?? "—"}</td>
                <td>{row.open_amount}</td>
                <td>{row.applied_amount}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3>Proposed journal lines</h3>
        {showsCollapsedOutcome ? (
          <p className="muted">
            Same-day full settlement collapse applies: allocation is recorded in settlement breakdown; the
            collapsed journal lines shown here do not carry per-line obligation ids.
          </p>
        ) : null}
        <table className="journal-lines" aria-label="Proposed journal lines">
          <thead>
            <tr>
              <th>Account</th>
              <th>Party</th>
              <th>Amount</th>
              <th>Obligation</th>
            </tr>
          </thead>
          <tbody>
            {proposedRows.map((row, index) => (
              <tr key={`${row.account}-${row.amount}-${index}`}>
                <td>{row.account}</td>
                <td>{row.party}</td>
                <td>{row.amount}</td>
                <td>{row.obligation}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}

        <div className="dialog-actions">
          <button type="button" className="button-secondary" disabled={saving} onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="button-secondary" disabled={saving} onClick={() => void onDecline()}>
            {saving ? "Posting…" : "Decline — post without settlement"}
          </button>
          <button type="button" disabled={saving} onClick={() => void onAccept()}>
            {saving ? "Posting…" : "Accept — post with settlement"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
