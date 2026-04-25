import { useMemo, useState } from "react";

import type { Account } from "../api/accounts";
import type { JournalEntryWrite } from "../api/journalEntries";
import { accountsForJournalLinePickers } from "../journal/accountSelect";

export interface LineDraft {
  key: string;
  account_id: number | "";
  amount: string;
  /** From GET /journal-entries/:id so the row stays labeled if chart cache is stale. */
  account_name?: string;
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

const BALANCE_EPS = 1e-9;

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

  const selectableAccounts = useMemo(() => {
    const base = accountsForJournalLinePickers(accounts, lineAccountIds);
    const byId = new Map(base.map((a) => [a.id, a]));
    for (const line of lines) {
      const hint = line.account_name?.trim();
      if (typeof line.account_id === "number" && line.account_id > 0 && hint && !byId.has(line.account_id)) {
        byId.set(line.account_id, {
          id: line.account_id,
          name: hint,
          type: "asset",
          is_active: true,
          created_at: "1970-01-01T00:00:00Z",
          updated_at: "1970-01-01T00:00:00Z",
        });
      }
    }
    return Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [accounts, lineAccountIds, lines]);

  const material = useMemo(() => materialJournalLines(lines), [lines]);
  const { sum: runningSum, complete: amountsComplete } = sumParsedAmounts(lines);
  const balanced = isBalanced(lines);
  const hasMinimumMaterialLines = material.length >= 2;

  function addLine() {
    setLines((prev) => [...prev, { key: newLineKey(), account_id: "", amount: "" }]);
  }

  function removeLine(key: string) {
    setLines((prev) => (prev.length <= 2 ? prev : prev.filter((l) => l.key !== key)));
  }

  function updateLine(key: string, patch: Partial<Pick<LineDraft, "account_id" | "amount">>) {
    setLines((prev) =>
      prev.map((l) => {
        if (l.key !== key) {
          return l;
        }
        const next: LineDraft = { ...l, ...patch };
        if ("account_id" in patch && patch.account_id !== l.account_id) {
          delete next.account_name;
        }
        return next;
      }),
    );
  }

  async function handleSubmit() {
    setClientError(null);
    setApiError(null);

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
    if (!amountsComplete) {
      setClientError("Enter a valid non-zero amount on every line that has an account.");
      return;
    }
    if (!balanced) {
      setClientError("Debits and credits must balance (line amounts must sum to zero).");
      return;
    }

    const payload: JournalEntryWrite = {
      entry_date: entryDate,
      description: description.trim() === "" ? null : description.trim(),
      lines: material.map((l) => ({
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
