import { useEffect, useMemo, useRef, useState } from "react";

import type { Account } from "../api/accounts";
import type { Cheque } from "../api/cheques";
import type { Party } from "../api/parties";
import {
  deleteJournalEntryReviewMessage,
  type JournalEntryReviewMessage,
  type JournalEntrySettlementAllocationOut,
  type JournalEntryWrite,
} from "../api/journalEntries";
import { listOpenObligations, type LedgerSettings, type Obligation } from "../api/settlements";
import { accountsForLinePicker } from "../journal/accountSelect";
import {
  applyObligationSelection,
  filterObligationsForLine,
  formatObligationOptionLabel,
} from "../journal/settlementUtils";
import { useJournalEntryFormShortcuts } from "../hooks/useJournalEntryFormShortcuts";
import {
  closeActionTooltip,
  discardActionTooltip,
  discardAriaKeyShortcuts,
  saveActionTooltip,
  saveAriaKeyShortcuts,
} from "../lib/keyboardHints";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";

export interface LineDraft {
  key: string;
  account_id: number | "";
  party_id: number | "";
  amount: string;
  obligation_id?: number | "";
  /** From GET /journal-entries/:id for saved obligation dropdown labels. */
  obligation_source_entry_summary?: string | null;
  /** From GET /journal-entries/:id so the row stays labeled if chart cache is stale. */
  account_name?: string;
  party_name?: string;
}

function newLineKey(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function emptyLines(count: number): LineDraft[] {
  return Array.from({ length: count }, () => ({
    key: newLineKey(),
    account_id: "",
    party_id: "",
    amount: "",
    obligation_id: "",
  }));
}

function parseAmount(value: string): number | null {
  const t = value.trim();
  if (t === "" || t === "-" || t === "." || t === "-.") {
    return null;
  }
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** Credit line amount for a positive cheque face amount (+ debit / − credit convention). */
function creditAmountFromChequeFace(amount: string): string {
  const t = amount.trim();
  if (t.startsWith("-")) {
    return t.slice(1);
  }
  return t === "" ? "" : `-${t}`;
}

/** Lines that have both an account and a non-empty amount string (may still be invalid number). */
export function materialJournalLines(lines: LineDraft[]): LineDraft[] {
  return lines.filter((l) => l.account_id !== "" && l.amount.trim() !== "");
}

/** Sum of parsed amounts for material lines only; `complete` means every material line parses. */
export function sumParsedAmounts(lines: LineDraft[]): { sum: number; complete: boolean } {
  const material = materialJournalLines(lines);
  let sum = 0;
  let complete = material.length > 0;
  for (const line of material) {
    const n = parseAmount(line.amount);
    if (n === null) {
      complete = false;
      continue;
    }
    sum += n;
  }
  return { sum, complete };
}

/** Sum of positive line amounts (debits) and absolute sum of negative amounts (credits). */
export function debitCreditTotals(lines: LineDraft[]): {
  debit: number;
  credit: number;
  complete: boolean;
} {
  const material = materialJournalLines(lines);
  let debit = 0;
  let credit = 0;
  let complete = material.length > 0;
  for (const line of material) {
    const n = parseAmount(line.amount);
    if (n === null) {
      complete = false;
      continue;
    }
    if (n > BALANCE_EPS) {
      debit += n;
    } else if (n < -BALANCE_EPS) {
      credit += -n;
    }
  }
  return { debit, credit, complete };
}

/**
 * True when every material line parses, debits equal credits, and both match the cheque face magnitude.
 */
export function linesMatchChequeFaceAmount(lines: LineDraft[], chequeAmountStr: string): boolean {
  if (materialJournalLines(lines).length === 0) {
    return true;
  }
  const face = parseAmount(chequeAmountStr.trim());
  if (face === null) {
    return false;
  }
  const { debit, credit, complete } = debitCreditTotals(lines);
  if (!complete) {
    return false;
  }
  if (Math.abs(debit - credit) > BALANCE_EPS) {
    return false;
  }
  const mag = Math.abs(face);
  return Math.abs(debit - mag) < BALANCE_EPS && Math.abs(credit - mag) < BALANCE_EPS;
}

const BALANCE_EPS = 1e-9;

function formatConfirmCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function isBalanced(lines: LineDraft[]): boolean {
  const material = materialJournalLines(lines);
  if (material.length < 2) {
    return false;
  }
  const { sum, complete } = sumParsedAmounts(lines);
  if (!complete) {
    return false;
  }
  for (const line of material) {
    const n = parseAmount(line.amount);
    if (n === null || Math.abs(n) < BALANCE_EPS) {
      return false;
    }
  }
  return Math.abs(sum) < BALANCE_EPS;
}

export interface JournalEntryFormProps {
  mode: "create" | "edit";
  accounts: Account[];
  parties: Party[];
  initialEntryDate: string;
  initialSummary: string;
  initialDescription: string;
  reviewMessages: JournalEntryReviewMessage[];
  initialLines: LineDraft[] | null;
  /** Set in edit mode so review messages can be cleared via the API. */
  entryId?: number | null;
  /** Called after a review message is removed (refetch entry in the parent). */
  onReviewMessagesChanged?: () => void | Promise<void>;
  onSubmit: (payload: JournalEntryWrite) => Promise<void>;
  /** Esc / Back: return to list without saving. */
  onCancel: () => void;
  /** Ctrl/Cmd+Shift+D: restore draft to last loaded values in place. */
  onRevert: () => void;
  /** Shown in edit mode to open the journal entry attachments dialog. */
  onOpenAttachments?: () => void;
  /** Open cheques (and optionally the entry’s linked cleared cheque when editing). */
  chequeLinkChoices?: Cheque[];
  initialChequeId?: number | null;
  ledgerSettings?: LedgerSettings | null;
  planTargetAccountByPlanId?: Map<number, number>;
  accrualPlanId?: number | null;
  accrualPlanName?: string | null;
  settlementAllocations?: JournalEntrySettlementAllocationOut[];
}

export function JournalEntryForm({
  mode,
  accounts,
  parties,
  initialEntryDate,
  initialSummary,
  initialDescription,
  reviewMessages,
  initialLines,
  entryId = null,
  onReviewMessagesChanged,
  onSubmit,
  onCancel,
  onRevert,
  onOpenAttachments,
  chequeLinkChoices = [],
  initialChequeId = null,
  ledgerSettings = null,
  planTargetAccountByPlanId = new Map(),
  accrualPlanId = null,
  accrualPlanName = null,
  settlementAllocations = [],
}: JournalEntryFormProps) {
  const isAccrualEntry = accrualPlanId != null;
  const [entryDate, setEntryDate] = useState(initialEntryDate);
  const [summary, setSummary] = useState(initialSummary);
  const [description, setDescription] = useState(initialDescription);
  const [newReviewNote, setNewReviewNote] = useState("");
  const [lines, setLines] = useState<LineDraft[]>(() =>
    initialLines && initialLines.length > 0 ? initialLines : emptyLines(2),
  );
  const [linkedChequeId, setLinkedChequeId] = useState<number | null>(() => initialChequeId ?? null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dismissingId, setDismissingId] = useState<number | null>(null);
  const [obligationsByParty, setObligationsByParty] = useState<Map<number, Obligation[]>>(
    () => new Map(),
  );
  const formRef = useRef<HTMLFormElement | null>(null);
  const handleSubmitForShortcutRef = useRef<() => Promise<void>>(async () => {});
  const onRevertForShortcutRef = useRef(onRevert);
  onRevertForShortcutRef.current = onRevert;
  const onCancelForShortcutRef = useRef(onCancel);
  onCancelForShortcutRef.current = onCancel;
  const isMac = isMacLikeUserAgent();

  const loadedAccountIdByLineKey = useMemo(() => {
    const m = new Map<string, number>();
    if (initialLines) {
      for (const l of initialLines) {
        if (typeof l.account_id === "number" && l.account_id > 0) {
          m.set(l.key, l.account_id);
        }
      }
    }
    return m;
  }, [initialLines]);

  const accountsById = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);

  const partyIdsOnLines = useMemo(() => {
    const ids = new Set<number>();
    for (const line of lines) {
      if (typeof line.party_id === "number" && line.party_id > 0) {
        ids.add(line.party_id);
      }
    }
    return [...ids];
  }, [lines]);

  const partyIdsKey = partyIdsOnLines.join(",");

  useEffect(() => {
    if (isAccrualEntry || partyIdsKey === "") {
      return;
    }
    for (const partyId of partyIdsOnLines) {
      void listOpenObligations(partyId)
        .then((rows) => {
          setObligationsByParty((prev) => {
            if (prev.has(partyId)) {
              return prev;
            }
            const next = new Map(prev);
            next.set(partyId, rows);
            return next;
          });
        })
        .catch(() => {
          setObligationsByParty((prev) => {
            if (prev.has(partyId)) {
              return prev;
            }
            const next = new Map(prev);
            next.set(partyId, []);
            return next;
          });
        });
    }
  }, [isAccrualEntry, partyIdsKey, partyIdsOnLines]);

  const obligationById = useMemo(() => {
    const map = new Map<number, Obligation>();
    for (const rows of obligationsByParty.values()) {
      for (const row of rows) {
        map.set(row.id, row);
      }
    }
    return map;
  }, [obligationsByParty]);

  const selectableParties = useMemo(() => {
    const byId = new Map(parties.map((p) => [p.id, p]));
    for (const line of lines) {
      const hint = line.party_name?.trim();
      if (typeof line.party_id === "number" && line.party_id > 0 && hint && !byId.has(line.party_id)) {
        byId.set(line.party_id, {
          id: line.party_id,
          name: hint,
          role: "other",
          is_active: true,
          match_patterns: [],
          created_at: "1970-01-01T00:00:00Z",
          updated_at: "1970-01-01T00:00:00Z",
        });
      }
    }
    return Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [parties, lines]);

  const material = useMemo(() => materialJournalLines(lines), [lines]);
  const { sum: runningSum, complete: amountsComplete } = sumParsedAmounts(lines);
  const balanced = isBalanced(lines);
  const hasMinimumMaterialLines = material.length >= 2;

  function addLine() {
    setLines((prev) => [
      ...prev,
      { key: newLineKey(), account_id: "", party_id: "", amount: "", obligation_id: "" },
    ]);
  }

  function removeLine(key: string) {
    setLines((prev) => (prev.length <= 2 ? prev : prev.filter((l) => l.key !== key)));
  }

  function applyChequeAutoFill(ch: Cheque) {
    setLinkedChequeId(ch.id);
    setSummary(ch.summary);
    const face = ch.amount.trim();
    const debitParty = ch.party_id != null ? ch.party_id : "";
    setLines([
      {
        key: newLineKey(),
        account_id: ch.debit_account_id,
        party_id: debitParty,
        amount: face.startsWith("-") ? face.slice(1) : face,
        obligation_id: "",
      },
      {
        key: newLineKey(),
        account_id: ch.credit_account_id,
        party_id: "",
        amount: creditAmountFromChequeFace(face),
        obligation_id: "",
      },
    ]);
  }

  function setObligationForLine(key: string, obligationId: number | "") {
    if (ledgerSettings == null) {
      return;
    }
    setLines((prev) => {
      const index = prev.findIndex((l) => l.key === key);
      if (index === -1) {
        return prev;
      }
      const line = prev[index]!;
      if (obligationId === "") {
        return prev.map((l) =>
          l.key === key ? { ...l, obligation_id: "", obligation_source_entry_summary: null } : l,
        );
      }
      const obligation = obligationById.get(obligationId);
      if (obligation == null) {
        return prev;
      }
      const applied = applyObligationSelection({
        line,
        obligation,
        entryDate,
        settings: ledgerSettings,
        accountsById,
      });
      const updated: LineDraft = {
        ...line,
        obligation_id: obligationId,
        obligation_source_entry_summary: obligation.source_entry_summary,
        account_id: applied.account_id,
        party_id: applied.party_id,
        amount: applied.amount,
      };
      const next = [...prev];
      next[index] = updated;
      if (applied.remainderLine != null) {
        next.splice(index + 1, 0, {
          key: newLineKey(),
          account_id: applied.remainderLine.account_id,
          party_id: applied.remainderLine.party_id,
          amount: applied.remainderLine.amount,
          obligation_id: "",
        });
      }
      return next;
    });
  }

  function updateLine(
    key: string,
    patch: Partial<Pick<LineDraft, "account_id" | "party_id" | "amount" | "obligation_id">>,
  ) {
    setLines((prev) =>
      prev.map((l) => {
        if (l.key !== key) {
          return l;
        }
        const next: LineDraft = { ...l, ...patch };
        if ("account_id" in patch && patch.account_id !== l.account_id) {
          delete next.account_name;
        }
        if ("party_id" in patch && patch.party_id !== l.party_id) {
          delete next.party_name;
        }
        return next;
      }),
    );
  }

  async function handleSubmit() {
    setClientError(null);
    setApiError(null);

    const trimmedNote = newReviewNote.trim();

    for (const line of lines) {
      const hasAmt = line.amount.trim() !== "";
      const hasAcct = line.account_id !== "";
      if ((hasAmt || hasAcct) && !(hasAmt && hasAcct)) {
        setClientError("Each journal line must have both an account and a non-zero amount.");
        return;
      }
    }

    if (material.length < 2) {
      setClientError("Add at least two complete lines (account and amount on each) before posting.");
      return;
    }
    if (!summary.trim()) {
      setClientError("Summary is required.");
      return;
    }
    if (!amountsComplete) {
      setClientError("Enter a valid non-zero amount on every line that has an account.");
      return;
    }
    if (!balanced) {
      setClientError("Debits and credits must balance (line amounts must sum to zero).");
      return;
    }

    const requiresReview = reviewMessages.length > 0 || Boolean(trimmedNote);
    const payload: JournalEntryWrite = {
      entry_date: entryDate,
      summary: summary.trim(),
      description: description.trim() === "" ? null : description.trim(),
      lines: material.map((l) => {
        const row = {
          account_id: l.account_id as number,
          party_id: l.party_id === "" ? null : l.party_id,
          amount: l.amount.trim(),
          ...(l.obligation_id !== "" && l.obligation_id != null
            ? { obligation_id: l.obligation_id }
            : {}),
        };
        return row;
      }),
      requires_review: requiresReview,
      review_messages: trimmedNote ? [trimmedNote] : [],
      cheque_id: linkedChequeId,
    };

    setSubmitting(true);
    try {
      await onSubmit(payload);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSubmitting(false);
    }
  }

  handleSubmitForShortcutRef.current = handleSubmit;

  useJournalEntryFormShortcuts({
    formActive: true,
    canSave: balanced,
    saving: submitting,
    onSave: () => void handleSubmitForShortcutRef.current(),
    onRevert: () => onRevertForShortcutRef.current(),
    onClose: () => onCancelForShortcutRef.current(),
  });

  const hasZeroLine =
    amountsComplete &&
    material.some((l) => {
      const n = parseAmount(l.amount);
      return n !== null && Math.abs(n) < BALANCE_EPS;
    });

  const balanceLabel = !amountsComplete
    ? "Enter amounts on each line to see balance."
    : hasZeroLine
      ? "Each line needs a non-zero amount."
      : Math.abs(runningSum) < BALANCE_EPS
        ? "Balanced — ready to post."
        : `Unbalanced by ${runningSum > 0 ? "+" : ""}${runningSum.toFixed(4)} (debits +, credits −; must sum to 0).`;

  return (
    <form
      ref={formRef}
      className="journal-form"
      onSubmit={(e) => {
        e.preventDefault();
        void handleSubmit();
      }}
    >
      <div className="journal-form-header">
        <h2>{mode === "create" ? "New journal entry" : "Journal entry details"}</h2>
        <div className="journal-form-header-actions">
          {mode === "edit" && onOpenAttachments ? (
            <button type="button" className="button-secondary" onClick={onOpenAttachments}>
              Attachments
            </button>
          ) : null}
          <button
            type="button"
            className="button-secondary"
            onClick={onCancel}
            title={closeActionTooltip(isMac)}
            aria-label={closeActionTooltip(isMac)}
          >
            Back to list
          </button>
          <button
            type="button"
            className="button-secondary"
            onClick={onRevert}
            title={discardActionTooltip(isMac)}
            aria-label={discardActionTooltip(isMac)}
            aria-keyshortcuts={discardAriaKeyShortcuts(isMac)}
          >
            {discardActionTooltip(isMac)}
          </button>
        </div>
      </div>

      {isAccrualEntry ? (
        <div className="banner-info journal-accrual-banner" role="status">
          Accrual plan entry: <strong>{accrualPlanName ?? `Plan #${accrualPlanId}`}</strong> — fields
          are read-only. Settlement changes are not available here.
        </div>
      ) : null}

      {isAccrualEntry && settlementAllocations.length > 0 ? (
        <div className="journal-settlement-allocations-readonly">
          <h3>Settlement allocations</h3>
          <table className="journal-entry-list" aria-label="Settlement allocations on this entry">
            <thead>
              <tr>
                <th>Obligation</th>
                <th>Amount</th>
              </tr>
            </thead>
            <tbody>
              {settlementAllocations.map((row) => (
                <tr key={row.id}>
                  <td>#{row.obligation_id}</td>
                  <td>{row.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <label>
        Entry date
        <input
          aria-label="Entry date"
          type="date"
          value={entryDate}
          onChange={(e) => setEntryDate(e.target.value)}
          required
          disabled={isAccrualEntry}
        />
      </label>

      <label>
        Summary
        <input
          aria-label="Entry summary"
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="e.g. June 2026 Rent Accrual - Acme Yard Maintenance"
          maxLength={200}
          required
          disabled={isAccrualEntry}
        />
      </label>

      <label>
        Description (optional)
        <input
          aria-label="Entry description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. April rent — Unit 2"
          maxLength={500}
          disabled={isAccrualEntry}
        />
      </label>

      <label>
        Link open cheque (optional)
        <select
          aria-label="Link open cheque"
          disabled={isAccrualEntry}
          value={linkedChequeId == null ? "" : String(linkedChequeId)}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "") {
              setLinkedChequeId(null);
              return;
            }
            const id = Number(v);
            const ch = chequeLinkChoices.find((c) => c.id === id);
            if (ch) {
              const hasMaterial = materialJournalLines(lines).length > 0;
              const needsConfirm = hasMaterial && !linesMatchChequeFaceAmount(lines, ch.amount);
              if (needsConfirm) {
                const { debit, credit, complete } = debitCreditTotals(lines);
                const face = parseAmount(ch.amount.trim());
                const faceLabel =
                  face === null ? ch.amount.trim() || "(invalid)" : formatConfirmCurrency(Math.abs(face));
                const detail = complete
                  ? `Debit total ${formatConfirmCurrency(debit)}, credit total ${formatConfirmCurrency(credit)}, cheque amount (absolute) ${faceLabel}.`
                  : "Some line amounts are missing or invalid.";
                const ok = window.confirm(
                  `This entry's amounts do not match the cheque face (${faceLabel}). ${detail} Replace the summary and lines with data from the cheque register?`,
                );
                if (!ok) {
                  return;
                }
              }
              applyChequeAutoFill(ch);
            } else {
              setLinkedChequeId(id);
            }
          }}
        >
          <option value="">None</option>
          {chequeLinkChoices.map((c) => (
            <option key={c.id} value={c.id}>
              #{c.cheque_number} — {c.summary} ({c.status})
            </option>
          ))}
        </select>
      </label>
      <p className="muted journal-cheque-hint">
        Choosing a cheque fills summary and lines from the register (debit expense / credit bank). Saving posts the
        clearing entry and marks the cheque <strong>cleared</strong>. Clear this field to unlink.
      </p>

      {reviewMessages.length > 0 ? (
        <div className="journal-review-messages" role="region" aria-label="Review messages">
          <ul className="journal-review-messages-list">
            {reviewMessages.map((m) => (
              <li
                key={m.id}
                className={`journal-review-message-card${
                  mode === "edit" && entryId != null ? " journal-review-message-card--dismissable" : ""
                }`}
              >
                {mode === "edit" && entryId != null ? (
                  <button
                    type="button"
                    className="journal-review-message-dismiss"
                    disabled={dismissingId === m.id}
                    title={dismissingId === m.id ? "Clearing…" : "Dismiss this review message"}
                    aria-label={
                      dismissingId === m.id
                        ? "Clearing review message"
                        : `Clear review message: ${m.message.slice(0, 80)}`
                    }
                    onClick={() => {
                      void (async () => {
                        setApiError(null);
                        setDismissingId(m.id);
                        try {
                          await deleteJournalEntryReviewMessage(entryId, m.id);
                          await onReviewMessagesChanged?.();
                        } catch (err) {
                          setApiError(err instanceof Error ? err.message : "Could not clear message");
                        } finally {
                          setDismissingId(null);
                        }
                      })();
                    }}
                  >
                    <svg
                      className="journal-review-message-dismiss-icon"
                      width="16"
                      height="16"
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
                ) : null}
                <p className="journal-review-message-text">{m.message}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <label>
        Add review note (optional)
        <textarea
          aria-label="New review message"
          className="journal-review-note-input"
          rows={2}
          value={newReviewNote}
          onChange={(e) => setNewReviewNote(e.target.value)}
          placeholder="Each save can append one new reason (e.g. confirm allocation)."
          disabled={isAccrualEntry}
        />
      </label>
      <p className="muted journal-review-hint">
        Reasons you add are stored separately. Clear a message when it no longer applies; when none remain, the entry is
        no longer flagged for review.
      </p>

      <div
        className={`balance-banner ${balanced && hasMinimumMaterialLines ? "balance-ok" : "balance-bad"}`}
      >
        <strong>Running total:</strong> {runningSum.toFixed(4)} — {balanceLabel}
      </div>

      <div className="journal-lines-header">
        <h3>Lines</h3>
        {!isAccrualEntry ? (
          <button type="button" className="button-secondary" onClick={addLine}>
            Add line
          </button>
        ) : null}
      </div>

      <table className="journal-lines">
        <thead>
          <tr>
            <th>Account</th>
            <th>Party (optional)</th>
            {!isAccrualEntry ? <th>Obligation (optional)</th> : <th>Obligation</th>}
            <th>Amount (+ debit, − credit)</th>
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const obligationLocked =
              !isAccrualEntry && line.obligation_id !== "" && line.obligation_id != null;
            const partyObligations =
              typeof line.party_id === "number"
                ? (obligationsByParty.get(line.party_id) ?? [])
                : [];
            const filtered = filterObligationsForLine(
              partyObligations,
              line,
              accountsById,
              planTargetAccountByPlanId,
            );
            const obligationOptions = filtered.obligations;
            const selectedObligationId =
              line.obligation_id === "" || line.obligation_id == null
                ? ""
                : String(line.obligation_id);
            return (
              <tr key={line.key}>
                <td>
                  <select
                    aria-label={`Account for line ${line.key}`}
                    value={line.account_id === "" ? "" : String(line.account_id)}
                    disabled={isAccrualEntry || obligationLocked}
                    onChange={(e) => {
                      const v = e.target.value;
                      updateLine(line.key, { account_id: v === "" ? "" : Number(v) });
                    }}
                  >
                    <option value="">Select account…</option>
                    {accountsForLinePicker(
                      accounts,
                      line,
                      loadedAccountIdByLineKey.get(line.key) ?? null,
                    ).map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                        {!a.is_active ? " (inactive)" : ""}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`Party for line ${line.key}`}
                    value={line.party_id === "" ? "" : String(line.party_id)}
                    disabled={isAccrualEntry || obligationLocked}
                    onChange={(e) => {
                      const v = e.target.value;
                      updateLine(line.key, { party_id: v === "" ? "" : Number(v) });
                    }}
                  >
                    <option value="">No party</option>
                    {selectableParties
                      .filter((p) => p.is_active || p.id === line.party_id)
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                          {!p.is_active ? " (inactive)" : ""}
                        </option>
                      ))}
                  </select>
                </td>
                <td>
                  {isAccrualEntry ? (
                    <span className="muted">
                      {line.obligation_id !== "" && line.obligation_id != null
                        ? `#${line.obligation_id}`
                        : "—"}
                    </span>
                  ) : (
                    <>
                      <select
                        aria-label={`Obligation for line ${line.key}`}
                        value={selectedObligationId}
                        disabled={line.party_id === "" || ledgerSettings == null}
                        onChange={(e) => {
                          const v = e.target.value;
                          setObligationForLine(line.key, v === "" ? "" : Number(v));
                        }}
                      >
                        <option value="">No obligation</option>
                        {obligationOptions.map((o) => (
                          <option key={o.id} value={o.id}>
                            {formatObligationOptionLabel(o.id, o.source_entry_summary, {
                              kind: "open",
                              openAmount: o.open_amount,
                            })}
                          </option>
                        ))}
                        {selectedObligationId !== "" &&
                        !obligationOptions.some((o) => String(o.id) === selectedObligationId) ? (
                          <option value={selectedObligationId}>
                            {formatObligationOptionLabel(
                              Number(selectedObligationId),
                              line.obligation_source_entry_summary ??
                                obligationById.get(Number(selectedObligationId))
                                  ?.source_entry_summary,
                              { kind: "saved" },
                            )}
                          </option>
                        ) : null}
                      </select>
                    </>
                  )}
                </td>
                <td>
                  <input
                    aria-label={`Amount for line ${line.key}`}
                    inputMode="decimal"
                    value={line.amount}
                    onChange={(e) => updateLine(line.key, { amount: e.target.value })}
                    placeholder="100.00 or -100.00"
                    disabled={isAccrualEntry}
                  />
                </td>
                <td>
                  {!isAccrualEntry ? (
                    <button
                      type="button"
                      className="button-secondary"
                      disabled={lines.length <= 2}
                      onClick={() => removeLine(line.key)}
                    >
                      Remove
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {clientError && (
        <p className="error" role="alert">
          {clientError}
        </p>
      )}
      {apiError && (
        <p className="error" role="alert">
          {apiError}
        </p>
      )}

      {!isAccrualEntry ? (
      <button
        type="submit"
        disabled={submitting || !balanced}
        title={saveActionTooltip(isMac)}
        aria-label={
          submitting
            ? undefined
            : mode === "create"
              ? isMac
                ? "Post entry (⌘+S)"
                : "Post entry (Ctrl+S)"
              : isMac
                ? "Save changes (⌘+S)"
                : "Save changes (Ctrl+S)"
        }
        aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
      >
        {submitting ? "Saving…" : mode === "create" ? "Post entry" : "Save changes"}
      </button>
      ) : null}
    </form>
  );
}
