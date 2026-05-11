import { FormEvent, MouseEvent, useCallback, useEffect, useMemo, useState } from "react";

import type { Account } from "../api/accounts";
import {
  type Cheque,
  type ChequeListStatus,
  createCheque,
  listCheques,
  patchCheque,
} from "../api/cheques";
import type { Party } from "../api/parties";
import { type LedgerSettings, getLedgerSettings } from "../api/settlements";

interface ChequesSectionProps {
  accounts: Account[];
  parties: Party[];
}

function statusLabel(s: Cheque["status"]): string {
  return s;
}

function isCreditEligible(account: Account): boolean {
  return account.is_active && account.type === "asset";
}

function isDebitEligible(account: Account): boolean {
  return account.is_active && account.type !== "suspense";
}

function ineligibleLabel(account: Account): string {
  const tags: string[] = [account.type];
  if (!account.is_active) {
    tags.push("inactive");
  }
  return `${account.name} (${tags.join(", ")})`;
}

function eligibleLabel(account: Account): string {
  return `${account.name} (${account.type})`;
}

function pickEligibleDefault(defaultId: number | null, eligible: Account[]): string {
  if (defaultId == null) {
    return "";
  }
  return eligible.some((a) => a.id === defaultId) ? String(defaultId) : "";
}

interface PickerOption {
  account: Account;
  eligible: boolean;
}

function buildPickerOptions(
  eligible: Account[],
  allAccounts: Account[],
  currentId: number | null,
): PickerOption[] {
  const options: PickerOption[] = eligible.map((account) => ({ account, eligible: true }));
  if (currentId != null && !eligible.some((a) => a.id === currentId)) {
    const fallback = allAccounts.find((a) => a.id === currentId);
    if (fallback) {
      options.push({ account: fallback, eligible: false });
    }
  }
  return options;
}

export function ChequesSection({ accounts, parties }: ChequesSectionProps) {
  const [listStatus, setListStatus] = useState<ChequeListStatus>("open");
  const [cheques, setCheques] = useState<Cheque[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);

  const [isCreating, setIsCreating] = useState(false);
  const [selected, setSelected] = useState<Cheque | null>(null);

  const [creditId, setCreditId] = useState("");
  const [debitId, setDebitId] = useState("");
  const [summary, setSummary] = useState("");
  const [chequeNumber, setChequeNumber] = useState("");
  const [issueDate, setIssueDate] = useState("");
  const [amount, setAmount] = useState("");
  const [partyId, setPartyId] = useState("");

  const [formError, setFormError] = useState<string | null>(null);
  const [formBusy, setFormBusy] = useState(false);

  const [defaultCreditId, setDefaultCreditId] = useState<number | null>(null);
  const [defaultDebitId, setDefaultDebitId] = useState<number | null>(null);

  const eligibleCreditAccounts = useMemo(
    () =>
      accounts
        .filter(isCreditEligible)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [accounts],
  );

  const eligibleDebitAccounts = useMemo(
    () =>
      accounts
        .filter(isDebitEligible)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [accounts],
  );

  const partyOptions = useMemo(
    () => parties.filter((p) => p.is_active).sort((a, b) => a.name.localeCompare(b.name)),
    [parties],
  );

  const reloadList = useCallback(async () => {
    setListError(null);
    setListLoading(true);
    try {
      const rows = await listCheques({ status: listStatus });
      setCheques(rows);
      setSelected((prev) => {
        if (!prev) {
          return null;
        }
        return rows.find((c) => c.id === prev.id) ?? null;
      });
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load cheques");
      setCheques([]);
      setSelected(null);
    } finally {
      setListLoading(false);
    }
  }, [listStatus]);

  useEffect(() => {
    void reloadList();
  }, [reloadList]);

  const refreshDefaults = useCallback(async () => {
    try {
      const settings: LedgerSettings = await getLedgerSettings();
      setDefaultCreditId(settings.default_cheque_credit_account_id);
      setDefaultDebitId(settings.default_cheque_debit_account_id);
    } catch {
      // Defaults are an enhancement, not a hard dependency for the rest of the form.
      setDefaultCreditId(null);
      setDefaultDebitId(null);
    }
  }, []);

  useEffect(() => {
    void refreshDefaults();
  }, [refreshDefaults]);

  useEffect(() => {
    if (selected) {
      hydrateForm(selected);
    }
  }, [selected]);

  function hydrateForm(ch: Cheque) {
    setCreditId(String(ch.credit_account_id));
    setDebitId(String(ch.debit_account_id));
    setSummary(ch.summary);
    setChequeNumber(String(ch.cheque_number));
    setIssueDate(ch.issue_date);
    setAmount(ch.amount);
    setPartyId(ch.party_id != null ? String(ch.party_id) : "");
  }

  function clearForm() {
    setCreditId(pickEligibleDefault(defaultCreditId, eligibleCreditAccounts));
    setDebitId(pickEligibleDefault(defaultDebitId, eligibleDebitAccounts));
    setSummary("");
    setChequeNumber("");
    setIssueDate(new Date().toISOString().slice(0, 10));
    setAmount("");
    setPartyId("");
  }

  function handleNewCheque() {
    setFormError(null);
    setIsCreating(true);
    setSelected(null);
    clearForm();
  }

  function handleSelectRow(ch: Cheque) {
    setFormError(null);
    setIsCreating(false);
    setSelected(ch);
  }

  function accountName(id: number): string {
    return accounts.find((a) => a.id === id)?.name ?? `#${id}`;
  }

  function partyName(id: number | null): string {
    if (id == null) {
      return "—";
    }
    return parties.find((p) => p.id === id)?.name ?? `#${id}`;
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    if (!creditId || !debitId || !summary.trim() || !chequeNumber || !issueDate || !amount) {
      setFormError("Credit account, debit account, summary, cheque number, issue date, and amount are required.");
      return;
    }
    const num = Number(chequeNumber);
    if (!Number.isInteger(num) || num <= 0) {
      setFormError("Cheque number must be a positive integer.");
      return;
    }
    setFormBusy(true);
    try {
      if (isCreating || !selected) {
        const created = await createCheque({
          credit_account_id: Number(creditId),
          debit_account_id: Number(debitId),
          summary: summary.trim(),
          cheque_number: num,
          issue_date: issueDate,
          amount,
          party_id: partyId ? Number(partyId) : null,
        });
        setIsCreating(false);
        setSelected(created);
        await reloadList();
        await refreshDefaults();
      } else {
        const updated = await patchCheque(selected.id, {
          credit_account_id: Number(creditId),
          debit_account_id: Number(debitId),
          summary: summary.trim(),
          cheque_number: num,
          issue_date: issueDate,
          amount,
          party_id: partyId ? Number(partyId) : null,
        });
        setSelected(updated);
        await reloadList();
        await refreshDefaults();
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setFormBusy(false);
    }
  }

  const savedCheque = selected;
  const canVoidOrReopen = !isCreating && savedCheque != null;

  async function handleVoid() {
    if (!savedCheque || savedCheque.status !== "open") {
      return;
    }
    if (!window.confirm(`Void cheque #${savedCheque.cheque_number} (${savedCheque.summary})?`)) {
      return;
    }
    setFormError(null);
    setFormBusy(true);
    try {
      const updated = await patchCheque(savedCheque.id, { status: "void" });
      setSelected(updated);
      await reloadList();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Void failed");
    } finally {
      setFormBusy(false);
    }
  }

  async function handleReopen() {
    if (!savedCheque || savedCheque.status !== "void") {
      return;
    }
    if (!window.confirm(`Re-open cheque #${savedCheque.cheque_number} (${savedCheque.summary})?`)) {
      return;
    }
    setFormError(null);
    setFormBusy(true);
    try {
      const updated = await patchCheque(savedCheque.id, { status: "open" });
      setSelected(updated);
      await reloadList();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Re-open failed");
    } finally {
      setFormBusy(false);
    }
  }

  async function voidRow(ch: Cheque, e: MouseEvent<HTMLButtonElement>) {
    e.stopPropagation();
    if (ch.status !== "open") {
      return;
    }
    if (!window.confirm(`Void cheque #${ch.cheque_number} (${ch.summary})?`)) {
      return;
    }
    setFormError(null);
    try {
      const updated = await patchCheque(ch.id, { status: "void" });
      if (selected?.id === ch.id) {
        setSelected(updated);
      }
      await reloadList();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Void failed");
    }
  }

  async function reopenRow(ch: Cheque, e: MouseEvent<HTMLButtonElement>) {
    e.stopPropagation();
    if (ch.status !== "void") {
      return;
    }
    if (!window.confirm(`Re-open cheque #${ch.cheque_number} (${ch.summary})?`)) {
      return;
    }
    setFormError(null);
    try {
      const updated = await patchCheque(ch.id, { status: "open" });
      if (selected?.id === ch.id) {
        setSelected(updated);
      }
      await reloadList();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Re-open failed");
    }
  }

  const showForm = isCreating || selected != null;

  return (
    <>
      <section className="card journal-card-wide">
        <h2>Cheque register</h2>
        <p className="muted">
          New cheques are always <strong>open</strong>. <strong>Cleared</strong> is set only when a clearing entry is
          posted against this cheque. Use <strong>Void</strong> or <strong>Re-open</strong> for void workflow only.
        </p>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "end", marginBottom: "1rem" }}>
          <label>
            Status filter
            <select
              value={listStatus}
              onChange={(e) => setListStatus(e.target.value as ChequeListStatus)}
              aria-label="Filter cheques by status"
            >
              <option value="open">Open (default)</option>
              <option value="cleared">Cleared</option>
              <option value="void">Void</option>
              <option value="all">All</option>
            </select>
          </label>
          <button type="button" onClick={() => void reloadList()} disabled={listLoading}>
            Refresh list
          </button>
          <button type="button" onClick={handleNewCheque}>
            New cheque
          </button>
        </div>

        {listError && <p className="error-text">{listError}</p>}

        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>#</th>
                <th>Summary</th>
                <th>Issue</th>
                <th>Amount</th>
                <th>Credit</th>
                <th>Debit</th>
                <th>Party</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {listLoading && cheques.length === 0 ? (
                <tr>
                  <td colSpan={9} className="muted">
                    Loading…
                  </td>
                </tr>
              ) : cheques.length === 0 ? (
                <tr>
                  <td colSpan={9} className="muted">
                    No cheques for this filter.
                  </td>
                </tr>
              ) : (
                cheques.map((ch) => (
                  <tr
                    key={ch.id}
                    onClick={() => handleSelectRow(ch)}
                    style={{
                      cursor: "pointer",
                      background: selected?.id === ch.id ? "var(--bg-subtle)" : undefined,
                    }}
                  >
                    <td>{statusLabel(ch.status)}</td>
                    <td>{ch.cheque_number}</td>
                    <td>{ch.summary}</td>
                    <td>{ch.issue_date}</td>
                    <td>{ch.amount}</td>
                    <td>{accountName(ch.credit_account_id)}</td>
                    <td>{accountName(ch.debit_account_id)}</td>
                    <td>{partyName(ch.party_id)}</td>
                    <td>
                      {ch.status === "open" && (
                        <button type="button" className="button-link" onClick={(e) => void voidRow(ch, e)}>
                          Void
                        </button>
                      )}
                      {ch.status === "void" && (
                        <button type="button" className="button-link" onClick={(e) => void reopenRow(ch, e)}>
                          Re-open
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {showForm && (
        <section className="card journal-card-wide">
          <h2>{isCreating ? "New cheque" : `Edit cheque #${selected?.cheque_number}`}</h2>
          {!isCreating && selected && (
            <p>
              <strong>Status:</strong> {statusLabel(selected.status)}
              {selected.status === "cleared" && selected.cleared_date && (
                <span className="muted"> (cleared {selected.cleared_date})</span>
              )}
            </p>
          )}

          <form noValidate onSubmit={(e) => void handleSave(e)}>
            <label>
              Credit account (cheque)
              <select
                value={creditId}
                onChange={(e) => setCreditId(e.target.value)}
                required
                disabled={selected?.status === "cleared"}
              >
                <option value="">Select account</option>
                {buildPickerOptions(
                  eligibleCreditAccounts,
                  accounts,
                  selected ? selected.credit_account_id : null,
                ).map(({ account, eligible }) => (
                  <option key={account.id} value={account.id}>
                    {eligible ? eligibleLabel(account) : ineligibleLabel(account)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Debit account
              <select
                value={debitId}
                onChange={(e) => setDebitId(e.target.value)}
                required
                disabled={selected?.status === "cleared"}
              >
                <option value="">Select account</option>
                {buildPickerOptions(
                  eligibleDebitAccounts,
                  accounts,
                  selected ? selected.debit_account_id : null,
                ).map(({ account, eligible }) => (
                  <option key={account.id} value={account.id}>
                    {eligible ? eligibleLabel(account) : ineligibleLabel(account)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Summary
              <input value={summary} onChange={(e) => setSummary(e.target.value)} required disabled={selected?.status === "cleared"} />
            </label>
            <label>
              Cheque number
              <input
                type="number"
                min={1}
                step={1}
                value={chequeNumber}
                onChange={(e) => setChequeNumber(e.target.value)}
                required
                disabled={selected?.status === "cleared"}
              />
            </label>
            <label>
              Issue date
              <input
                type="date"
                value={issueDate}
                onChange={(e) => setIssueDate(e.target.value)}
                required
                disabled={selected?.status === "cleared"}
              />
            </label>
            <label>
              Amount
              <input value={amount} onChange={(e) => setAmount(e.target.value)} required disabled={selected?.status === "cleared"} />
            </label>
            <label>
              Party (optional)
              <select
                value={partyId}
                onChange={(e) => setPartyId(e.target.value)}
                disabled={selected?.status === "cleared"}
              >
                <option value="">None</option>
                {partyOptions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>

            {formError && <p className="error-text">{formError}</p>}

            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center" }}>
              <button type="submit" disabled={formBusy || selected?.status === "cleared"}>
                {isCreating ? "Create cheque" : "Save changes"}
              </button>
              {canVoidOrReopen && savedCheque.status === "open" && (
                <button type="button" onClick={() => void handleVoid()} disabled={formBusy}>
                  Void cheque
                </button>
              )}
              {canVoidOrReopen && savedCheque.status === "void" && (
                <button type="button" onClick={() => void handleReopen()} disabled={formBusy}>
                  Re-open cheque
                </button>
              )}
            </div>
          </form>
        </section>
      )}
    </>
  );
}
