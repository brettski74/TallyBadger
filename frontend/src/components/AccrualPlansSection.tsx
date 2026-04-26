import { FormEvent, useEffect, useMemo, useState } from "react";

import type { Account } from "../api/accounts";
import {
  createAccrualPlan,
  listAccrualPlans,
  previewAccrualPlan,
  type AccrualDirection,
  type AccrualFrequency,
  type AccrualPlan,
  type AccrualPlanWrite,
  type AccrualPreviewItem,
} from "../api/accrualPlans";
import type { Party } from "../api/parties";

const DAY_OPTIONS = [
  { label: "Monday", value: 0 },
  { label: "Tuesday", value: 1 },
  { label: "Wednesday", value: 2 },
  { label: "Thursday", value: 3 },
  { label: "Friday", value: 4 },
  { label: "Saturday", value: 5 },
  { label: "Sunday", value: 6 },
];

interface AccrualPlansSectionProps {
  accounts: Account[];
  parties: Party[];
}

export function AccrualPlansSection({ accounts, parties }: AccrualPlansSectionProps) {
  const [plans, setPlans] = useState<AccrualPlan[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [direction, setDirection] = useState<AccrualDirection>("revenue");
  const [partyId, setPartyId] = useState("");
  const [targetAccountId, setTargetAccountId] = useState("");
  const [bridgeAccountId, setBridgeAccountId] = useState("");
  const [frequency, setFrequency] = useState<AccrualFrequency>("monthly_day");
  const [dayOfWeek, setDayOfWeek] = useState("0");
  const [dayOfMonth, setDayOfMonth] = useState("1");
  const [monthOfYear, setMonthOfYear] = useState("1");
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState("0.00");
  const [summaryTemplate, setSummaryTemplate] = useState("{plan} {month}");
  const [descriptionTemplate, setDescriptionTemplate] = useState("");
  const [businessDayAdjust, setBusinessDayAdjust] = useState(false);

  const [previewRows, setPreviewRows] = useState<AccrualPreviewItem[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    async function loadPlans() {
      setLoading(true);
      setError(null);
      try {
        setPlans(await listAccrualPlans());
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load plans");
      } finally {
        setLoading(false);
      }
    }
    void loadPlans();
  }, []);

  const canCreate = useMemo(() => previewRows.length > 0 && !creating, [previewRows, creating]);
  const accountNameById = useMemo(
    () => new Map(accounts.map((account) => [account.id, account.name])),
    [accounts],
  );
  const partyNameById = useMemo(() => new Map(parties.map((party) => [party.id, party.name])), [parties]);
  const targetAccountOptions = useMemo(
    () => accounts.filter((a) => (direction === "revenue" ? a.type === "revenue" : a.type === "expense")),
    [accounts, direction],
  );
  const bridgeAccountOptions = useMemo(
    () => accounts.filter((a) => (direction === "revenue" ? a.type === "asset" : a.type === "liability")),
    [accounts, direction],
  );

  function validateAccountGuardrail(): string | null {
    const target = accounts.find((a) => String(a.id) === targetAccountId);
    const bridge = accounts.find((a) => String(a.id) === bridgeAccountId);
    if (!target || !bridge) {
      return "Select both a target and bridge account.";
    }
    if (direction === "revenue") {
      if (target.type !== "revenue") {
        return "Revenue plans require a revenue target account.";
      }
      if (bridge.type !== "asset") {
        return "Revenue plans require an asset bridge account (A/R).";
      }
    } else {
      if (target.type !== "expense") {
        return "Expense plans require an expense target account.";
      }
      if (bridge.type !== "liability") {
        return "Expense plans require a liability bridge account (A/P).";
      }
    }
    return null;
  }

  function buildPayload(): AccrualPlanWrite {
    const payload: AccrualPlanWrite = {
      name: name.trim(),
      direction,
      party_id: Number(partyId),
      target_account_id: Number(targetAccountId),
      bridge_account_id: Number(bridgeAccountId),
      frequency,
      start_date: startDate,
      end_date: endDate,
      amount,
      summary_template: summaryTemplate.trim(),
      description_template: descriptionTemplate.trim() ? descriptionTemplate.trim() : null,
      business_day_adjust: businessDayAdjust,
    };
    if (frequency === "weekly") {
      payload.day_of_week = Number(dayOfWeek);
    }
    if (frequency === "monthly_day" || frequency === "yearly") {
      payload.day_of_month = Number(dayOfMonth);
    }
    if (frequency === "yearly") {
      payload.month_of_year = Number(monthOfYear);
    }
    return payload;
  }

  async function handlePreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    const guardrailError = validateAccountGuardrail();
    if (guardrailError) {
      setSubmitError(guardrailError);
      setPreviewRows([]);
      return;
    }
    setPreviewing(true);
    try {
      const rows = await previewAccrualPlan(buildPayload());
      setPreviewRows(rows);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to preview plan");
      setPreviewRows([]);
    } finally {
      setPreviewing(false);
    }
  }

  async function handleCreatePlan() {
    setSubmitError(null);
    const guardrailError = validateAccountGuardrail();
    if (guardrailError) {
      setSubmitError(guardrailError);
      return;
    }
    setCreating(true);
    try {
      const created = await createAccrualPlan(buildPayload());
      setPlans((prev) => [created, ...prev]);
      setPreviewRows([]);
      setName("");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create plan");
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <section className="card journal-card-wide">
        <h2>Accrual plans</h2>
        <p className="muted">Preview generated accrual entries, then commit plan + entries together.</p>
        <form noValidate onSubmit={(e) => void handlePreview(e)}>
          <label>
            Plan name
            <input aria-label="Plan name" value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            Direction
            <select
              aria-label="Plan direction"
              value={direction}
              onChange={(e) => setDirection(e.target.value as AccrualDirection)}
            >
              <option value="revenue">revenue</option>
              <option value="expense">expense</option>
            </select>
          </label>
          <label>
            Party
            <select aria-label="Plan party" value={partyId} onChange={(e) => setPartyId(e.target.value)} required>
              <option value="">Select party</option>
              {parties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Target account
            <select
              aria-label="Target account"
              value={targetAccountId}
              onChange={(e) => setTargetAccountId(e.target.value)}
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
            Bridge account
            <select
              aria-label="Bridge account"
              value={bridgeAccountId}
              onChange={(e) => setBridgeAccountId(e.target.value)}
              required
            >
              <option value="">Select bridge account</option>
              {bridgeAccountOptions.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Frequency
            <select
              aria-label="Plan frequency"
              value={frequency}
              onChange={(e) => setFrequency(e.target.value as AccrualFrequency)}
            >
              <option value="weekly">weekly</option>
              <option value="monthly_day">monthly_day</option>
              <option value="yearly">yearly</option>
            </select>
          </label>
          {frequency === "weekly" && (
            <label>
              Day of week
              <select aria-label="Day of week" value={dayOfWeek} onChange={(e) => setDayOfWeek(e.target.value)}>
                {DAY_OPTIONS.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {(frequency === "monthly_day" || frequency === "yearly") && (
            <label>
              Day of month
              <input
                aria-label="Day of month"
                type="number"
                min={1}
                max={31}
                value={dayOfMonth}
                onChange={(e) => setDayOfMonth(e.target.value)}
              />
            </label>
          )}
          {frequency === "yearly" && (
            <label>
              Month of year
              <input
                aria-label="Month of year"
                type="number"
                min={1}
                max={12}
                value={monthOfYear}
                onChange={(e) => setMonthOfYear(e.target.value)}
              />
            </label>
          )}
          <label>
            Start date
            <input aria-label="Plan start date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            End date
            <input aria-label="Plan end date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
          <label>
            Amount
            <input aria-label="Plan amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label>
            Summary template
            <input
              aria-label="Summary template"
              value={summaryTemplate}
              onChange={(e) => setSummaryTemplate(e.target.value)}
            />
          </label>
          <label>
            Description template
            <input
              aria-label="Description template"
              value={descriptionTemplate}
              onChange={(e) => setDescriptionTemplate(e.target.value)}
            />
          </label>
          {(frequency === "monthly_day" || frequency === "yearly") && (
            <label className="checkbox">
              <input
                aria-label="Business day adjust"
                type="checkbox"
                checked={businessDayAdjust}
                onChange={(e) => setBusinessDayAdjust(e.target.checked)}
              />
              Roll weekends to Monday
            </label>
          )}
          <div className="form-actions-inline">
            <button type="submit" disabled={previewing}>
              {previewing ? "Previewing..." : "Preview entries"}
            </button>
            <button type="button" className="button-secondary" onClick={() => void handleCreatePlan()} disabled={!canCreate}>
              {creating ? "Creating..." : "Create plan"}
            </button>
          </div>
          {submitError && (
            <p className="error" role="alert">
              {submitError}
            </p>
          )}
        </form>
      </section>

      <section className="card journal-card-wide">
        <h2>Preview</h2>
        {previewRows.length === 0 ? (
          <p className="muted">No preview yet.</p>
        ) : (
          <table className="journal-entry-list" aria-label="Accrual preview">
            <thead>
              <tr>
                <th>Date</th>
                <th>Summary</th>
                <th>Parties</th>
                <th>Debit account</th>
                <th>Credit account</th>
                <th className="journal-list-amount">Amount</th>
              </tr>
            </thead>
            <tbody>
              {previewRows.map((row, idx) => {
                const lines = row.lines.map((line) => ({
                  ...line,
                  amountNumber: Number(line.amount),
                }));
                const debitLines = lines.filter((line) => line.amountNumber > 0);
                const creditLines = lines.filter((line) => line.amountNumber < 0);
                const debitLabel =
                  debitLines.length === 1
                    ? (accountNameById.get(debitLines[0].account_id) ?? `Account ${debitLines[0].account_id}`)
                    : debitLines.length > 1
                      ? "-- Split --"
                      : "—";
                const creditLabel =
                  creditLines.length === 1
                    ? (accountNameById.get(creditLines[0].account_id) ?? `Account ${creditLines[0].account_id}`)
                    : creditLines.length > 1
                      ? "-- Split --"
                      : "—";
                const amount = debitLines.reduce((acc, line) => acc + line.amountNumber, 0);
                const partyNames = Array.from(
                  new Set(
                    row.lines
                      .map((line) => (line.party_id ? partyNameById.get(line.party_id) : null))
                      .filter((name): name is string => Boolean(name)),
                  ),
                );
                return (
                  <tr key={`${row.entry_date}-${idx}`}>
                    <td>{row.entry_date}</td>
                    <td>{row.summary}</td>
                    <td>{partyNames.length > 0 ? partyNames.join(", ") : "—"}</td>
                    <td>{debitLabel}</td>
                    <td>{creditLabel}</td>
                    <td className="journal-list-amount">{amount.toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="card journal-card-wide">
        <h2>Existing plans</h2>
        {loading && <p>Loading plans...</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!loading && !error && plans.length === 0 && <p>No plans yet.</p>}
        {!loading && !error && plans.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Frequency</th>
                <th>Direction</th>
                <th>Range</th>
              </tr>
            </thead>
            <tbody>
              {plans.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>{p.frequency}</td>
                  <td>{p.direction}</td>
                  <td>
                    {p.start_date} to {p.end_date}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
