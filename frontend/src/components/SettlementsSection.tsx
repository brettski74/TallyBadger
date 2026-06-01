import { FormEvent, useEffect, useMemo, useState } from "react";

import type { Account } from "../api/accounts";
import type { Party } from "../api/parties";
import { createSettlement, listOpenObligations, type Obligation } from "../api/settlements";

interface SettlementsSectionProps {
  accounts: Account[];
  parties: Party[];
}

export function SettlementsSection({ accounts, parties }: SettlementsSectionProps) {
  const [partyId, setPartyId] = useState("");
  const [settlementType, setSettlementType] = useState<"receipt" | "payment">("receipt");
  const [eventDate, setEventDate] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState("0.00");
  const [cashAccountId, setCashAccountId] = useState("");
  const [note, setNote] = useState("");

  const [obligations, setObligations] = useState<Obligation[]>([]);
  const [allocations, setAllocations] = useState<Record<number, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);

  const cashOptions = useMemo(() => accounts.filter((account) => account.type === "asset"), [accounts]);

  useEffect(() => {
    async function loadObligations() {
      if (!partyId) {
        setObligations([]);
        setAllocations({});
        return;
      }
      try {
        const rows = await listOpenObligations(Number(partyId));
        const filtered = rows.filter((row) =>
          settlementType === "receipt" ? row.obligation_type === "receivable" : row.obligation_type === "payable",
        );
        setObligations(filtered);
        setAllocations(autoAllocateForAmount(amount, filtered));
      } catch (err) {
        setFormError(err instanceof Error ? err.message : "Failed to load obligations");
      }
    }
    void loadObligations();
  }, [partyId, settlementType]);

  useEffect(() => {
    setAllocations(autoAllocateForAmount(amount, obligations));
  }, [amount, obligations]);

  function autoAllocateForAmount(value: string, rows: Obligation[]): Record<number, string> {
    let remaining = Number(value);
    if (!Number.isFinite(remaining) || remaining <= 0) {
      return {};
    }
    const out: Record<number, string> = {};
    for (const row of rows) {
      if (remaining <= 0) {
        break;
      }
      const open = Number(row.open_amount);
      if (!Number.isFinite(open) || open <= 0) {
        continue;
      }
      const allocation = Math.min(open, remaining);
      out[row.id] = allocation.toFixed(2);
      remaining -= allocation;
    }
    return out;
  }

  async function handleSubmitSettlement(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setSubmitMessage(null);
    const nonZeroAllocations = obligations
      .map((obligation) => ({ obligation_id: obligation.id, amount: allocations[obligation.id] ?? "0" }))
      .filter((item) => Number(item.amount) > 0);
    if (!partyId || !cashAccountId || nonZeroAllocations.length === 0) {
      setFormError("Select party/cash account and allocate at least one obligation.");
      return;
    }
    try {
      const result = await createSettlement({
        party_id: Number(partyId),
        settlement_type: settlementType,
        event_date: eventDate,
        amount,
        cash_account_id: Number(cashAccountId),
        allocations: nonZeroAllocations,
        note: note.trim() || null,
      });
      setSubmitMessage(`Settlement posted (entry ${result.entry_id}).`);
      const rows = await listOpenObligations(Number(partyId));
      const filtered = rows.filter((row) =>
        settlementType === "receipt" ? row.obligation_type === "receivable" : row.obligation_type === "payable",
      );
      setObligations(filtered);
      setAllocations(autoAllocateForAmount(amount, filtered));
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to post settlement");
    }
  }

  return (
    <>
      <section className="card journal-card-wide">
        <p className="muted">
          A/R, A/P, unearned revenue, and prepaid expenses accounts are configured under{" "}
          <strong>Configuration</strong>.
        </p>
        <h2>Settle obligations</h2>
        <form noValidate onSubmit={(e) => void handleSubmitSettlement(e)}>
          <label>
            Party
            <select value={partyId} onChange={(e) => setPartyId(e.target.value)}>
              <option value="">Select party</option>
              {parties.map((party) => (
                <option key={party.id} value={party.id}>{party.name}</option>
              ))}
            </select>
          </label>
          <label>
            Settlement type
            <select value={settlementType} onChange={(e) => setSettlementType(e.target.value as "receipt" | "payment")}>
              <option value="receipt">receipt</option>
              <option value="payment">payment</option>
            </select>
          </label>
          <label>
            Date
            <input type="date" value={eventDate} onChange={(e) => setEventDate(e.target.value)} />
          </label>
          <label>
            Amount
            <input value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label>
            Cash account
            <select value={cashAccountId} onChange={(e) => setCashAccountId(e.target.value)}>
              <option value="">Select cash account</option>
              {cashOptions.map((account) => (
                <option key={account.id} value={account.id}>{account.name}</option>
              ))}
            </select>
          </label>
          <label>
            Note
            <input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <h3>Open obligations</h3>
          {obligations.length === 0 ? (
            <p className="muted">No matching open obligations.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Date</th>
                  <th>Summary</th>
                  <th>Type</th>
                  <th>Due</th>
                  <th>Open amount</th>
                  <th>Allocate</th>
                </tr>
              </thead>
              <tbody>
                {obligations.map((obligation) => (
                  <tr key={obligation.id}>
                    <td>{obligation.id}</td>
                    <td>{obligation.source_entry_date ?? "—"}</td>
                    <td>{obligation.source_entry_summary ?? "—"}</td>
                    <td>{obligation.obligation_type}</td>
                    <td>
                      {obligation.source_entry_date !== null &&
                      obligation.source_entry_date > eventDate
                        ? "future"
                        : "due"}
                    </td>
                    <td>{obligation.open_amount}</td>
                    <td>
                      <input
                        aria-label={`Allocate obligation ${obligation.id}`}
                        value={allocations[obligation.id] ?? ""}
                        onChange={(e) => setAllocations((prev) => ({ ...prev, [obligation.id]: e.target.value }))}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {settlementType === "receipt" && (
            <p className="muted">
              Receipts auto-allocate oldest-first; future portions flow through unearned revenue
              automatically.
            </p>
          )}
          {settlementType === "payment" && (
            <p className="muted">
              Payments auto-allocate oldest-first; future portions flow through prepaid expenses
              automatically.
            </p>
          )}
          <button type="submit">Post settlement</button>
          {formError && <p className="error" role="alert">{formError}</p>}
          {submitMessage && <p>{submitMessage}</p>}
        </form>
      </section>
    </>
  );
}
