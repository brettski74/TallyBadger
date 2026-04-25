import { useMemo, useState } from "react";

import type { Account } from "../api/accounts";
import type { JournalEntryWrite } from "../api/journalEntries";
import { accountsForJournalLinePickers } from "../journal/accountSelect";

export interface LineDraft {
  key: string;
  account_id: number | "";
  amount: string;
}

function newLineKey(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function emptyLines(count: number): LineDraft[] {
  return Array.from({ length: count }, () => ({
    key: newLineKey(),
    account_id: "",
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

/** Sum of parsed line amounts; lines with invalid input are skipped in the partial sum. */
export function sumParsedAmounts(lines: LineDraft[]): { sum: number; complete: boolean } {
  let sum = 0;
  let complete = true;
  for (const line of lines) {
    if (line.amount.trim() === "") {
      complete = false;
      continue;
    }
    const n = parseAmount(line.amount);
    if (n === null) {
      complete = false;
      continue;
    }
    sum += n;
  }
  return { sum, complete };
}

const BALANCE_EPS = 1e-9;

export function isBalanced(lines: LineDraft[]): boolean {
  if (lines.length < 2) {
    return false;
  }
  if (lines.some((l) => l.account_id === "")) {
    return false;
  }
  const { sum, complete } = sumParsedAmounts(lines);
  if (!complete) {
    return false;
  }
  for (const line of lines) {
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
  initialEntryDate: string;
  initialDescription: string;
  initialLines: LineDraft[] | null;
  onSubmit: (payload: JournalEntryWrite) => Promise<void>;
  onCancel: () => void;
}

export function JournalEntryForm({
  mode,
  accounts,
  initialEntryDate,
  initialDescription,
  initialLines,
  onSubmit,
  onCancel,
}: JournalEntryFormProps) {
  const [entryDate, setEntryDate] = useState(initialEntryDate);
  const [description, setDescription] = useState(initialDescription);
  const [lines, setLines] = useState<LineDraft[]>(() =>
    initialLines && initialLines.length > 0 ? initialLines : emptyLines(2),
  );
  const [clientError, setClientError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const lineAccountIds = useMemo(
    () =>
      lines
        .map((l) => l.account_id)
        .filter((id): id is number => typeof id === "number" && id > 0),
    [lines],
  );

  const selectableAccounts = useMemo(
    () => accountsForJournalLinePickers(accounts, lineAccountIds),
    [accounts, lineAccountIds],
  );

  const { sum: runningSum, complete: amountsComplete } = sumParsedAmounts(lines);
  const balanced = isBalanced(lines);
  const hasMinimumLines = lines.length >= 2;

  function addLine() {
    setLines((prev) => [...prev, { key: newLineKey(), account_id: "", amount: "" }]);
  }

  function removeLine(key: string) {
    setLines((prev) => (prev.length <= 2 ? prev : prev.filter((l) => l.key !== key)));
  }

  function updateLine(key: string, patch: Partial<Pick<LineDraft, "account_id" | "amount">>) {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  async function handleSubmit() {
    setClientError(null);
    setApiError(null);

    if (!hasMinimumLines) {
      setClientError("Add at least two lines before posting.");
      return;
    }
    if (lines.some((l) => l.account_id === "")) {
      setClientError("Select an account on every line.");
      return;
    }
    if (!amountsComplete) {
      setClientError("Enter a valid non-zero amount on every line.");
      return;
    }
    if (!balanced) {
      setClientError("Debits and credits must balance (line amounts must sum to zero).");
      return;
    }

    const payload: JournalEntryWrite = {
      entry_date: entryDate,
      description: description.trim() === "" ? null : description.trim(),
      lines: lines.map((l) => ({
        account_id: l.account_id as number,
        amount: l.amount.trim(),
      })),
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

  const hasZeroLine =
    amountsComplete &&
    lines.some((l) => {
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
      className="journal-form"
      onSubmit={(e) => {
        e.preventDefault();
        void handleSubmit();
      }}
    >
      <div className="journal-form-header">
        <h2>{mode === "create" ? "New journal entry" : "Edit journal entry"}</h2>
        <button type="button" className="button-secondary" onClick={onCancel}>
          Back to list
        </button>
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
        Description (optional)
        <input
          aria-label="Entry description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. April rent — Unit 2"
          maxLength={500}
        />
      </label>

      <div className={`balance-banner ${balanced && hasMinimumLines ? "balance-ok" : "balance-bad"}`}>
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
                  {selectableAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                      {!a.is_active ? " (inactive)" : ""}
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

      <button type="submit" disabled={submitting || !balanced}>
        {submitting ? "Saving…" : mode === "create" ? "Post entry" : "Save changes"}
      </button>
    </form>
  );
}
