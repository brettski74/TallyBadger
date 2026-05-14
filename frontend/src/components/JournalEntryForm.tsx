import { useEffect, useMemo, useRef, useState } from "react";

import type { Account } from "../api/accounts";
import type { Cheque } from "../api/cheques";
import type { Party } from "../api/parties";
import {
  deleteJournalEntryReviewMessage,
  type JournalEntryReviewMessage,
  type JournalEntryWrite,
} from "../api/journalEntries";
import { isTargetAssociatedWithForm } from "../hooks/useFormSaveDiscardShortcuts";
import { accountsForLinePicker } from "../journal/accountSelect";
import { saveActionTooltip, saveAriaKeyShortcuts } from "../lib/keyboardHints";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";

export interface LineDraft {
  key: string;
  account_id: number | "";
  party_id: number | "";
  amount: string;
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
  onCancel: () => void;
  /** Shown in edit mode to open the journal entry attachments dialog. */
  onOpenAttachments?: () => void;
  /** Open cheques (and optionally the entry’s linked cleared cheque when editing). */
  chequeLinkChoices?: Cheque[];
  initialChequeId?: number | null;
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
  onOpenAttachments,
  chequeLinkChoices = [],
  initialChequeId = null,
}: JournalEntryFormProps) {
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
  const formRef = useRef<HTMLFormElement | null>(null);
  const handleSubmitForShortcutRef = useRef<() => Promise<void>>(async () => {});
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
    setLines((prev) => [...prev, { key: newLineKey(), account_id: "", party_id: "", amount: "" }]);
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
      },
      {
        key: newLineKey(),
        account_id: ch.credit_account_id,
        party_id: "",
        amount: creditAmountFromChequeFace(face),
      },
    ]);
  }

  function updateLine(
    key: string,
    patch: Partial<Pick<LineDraft, "account_id" | "party_id" | "amount">>,
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
      lines: material.map((l) => ({
        account_id: l.account_id as number,
        party_id: l.party_id === "" ? null : l.party_id,
        amount: l.amount.trim(),
      })),
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

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (!isTargetAssociatedWithForm(target, formRef.current)) {
        return;
      }
      const saveChord =
        (e.key === "s" || e.key === "S") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
      if (!saveChord) {
        return;
      }
      if (submitting || !balanced) {
        return;
      }
      e.preventDefault();
      void handleSubmitForShortcutRef.current();
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [submitting, balanced]);

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
          <button type="button" className="button-secondary" onClick={onCancel}>
            Back to list
          </button>
        </div>
      </div>

      <label>
        Entry date
        <input
          aria-label="Entry date"
          type="date"
          value={entryDate}
          onChange={(e) => setEntryDate(e.target.value)}
          required
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
        />
      </label>

      <label>
        Link open cheque (optional)
        <select
          aria-label="Link open cheque"
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
        <button type="button" className="button-secondary" onClick={addLine}>
          Add line
        </button>
      </div>

      <table className="journal-lines">
        <thead>
          <tr>
            <th>Account</th>
            <th>Party (optional)</th>
            <th>Amount (+ debit, − credit)</th>
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.key}>
              <td>
                <select
                  aria-label={`Account for line ${line.key}`}
                  value={line.account_id === "" ? "" : String(line.account_id)}
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
                <input
                  aria-label={`Amount for line ${line.key}`}
                  inputMode="decimal"
                  value={line.amount}
                  onChange={(e) => updateLine(line.key, { amount: e.target.value })}
                  placeholder="100.00 or -100.00"
                />
              </td>
              <td>
                <button
                  type="button"
                  className="button-secondary"
                  disabled={lines.length <= 2}
                  onClick={() => removeLine(line.key)}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
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
    </form>
  );
}
