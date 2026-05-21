import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { FilePlus2, RefreshCcw } from "lucide-react";

import type { Account } from "../api/accounts";
import {
  createAccrualPlan,
  listAccrualPlans,
  previewAccrualPlan,
  type AccrualDirection,
  type AccrualFrequency,
  type AccrualPlan,
  type AccrualPlanSettlementStatus,
  type AccrualPlanWrite,
  type AccrualPreviewItem,
} from "../api/accrualPlans";
import type { Party } from "../api/parties";
import { TableRowIconButton } from "./TableRowIconButton";

const DAY_OPTIONS = [
  { label: "Monday", value: 0 },
  { label: "Tuesday", value: 1 },
  { label: "Wednesday", value: 2 },
  { label: "Thursday", value: 3 },
  { label: "Friday", value: 4 },
  { label: "Saturday", value: 5 },
  { label: "Sunday", value: 6 },
];

const SETTLEMENT_STATUS_OPTIONS: { value: AccrualPlanSettlementStatus; label: string }[] = [
  { value: "open", label: "Open (default)" },
  { value: "unsettled", label: "Unsettled" },
  { value: "partially_settled", label: "Partially settled" },
  { value: "settled", label: "Settled" },
  { value: "any", label: "Any" },
];

interface AccrualPlansSectionProps {
  accounts: Account[];
  parties: Party[];
}

export function AccrualPlansSection({ accounts, parties }: AccrualPlansSectionProps) {
  const [plans, setPlans] = useState<AccrualPlan[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [settlementStatus, setSettlementStatus] = useState<AccrualPlanSettlementStatus>("open");
  const [filterPartyId, setFilterPartyId] = useState("");
  const [filterTargetAccountId, setFilterTargetAccountId] = useState("");
  const [filterBridgeAccountId, setFilterBridgeAccountId] = useState("");
  const [filterName, setFilterName] = useState("");
  const [filterFromDate, setFilterFromDate] = useState("");
  const [filterToDate, setFilterToDate] = useState("");

  const [filterPartyIds, setFilterPartyIds] = useState<number[]>([]);
  const [filterTargetAccountIds, setFilterTargetAccountIds] = useState<number[]>([]);
  const [filterBridgeAccountIds, setFilterBridgeAccountIds] = useState<number[]>([]);

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

  const accountNameById = useMemo(
    () => new Map(accounts.map((account) => [account.id, account.name])),
    [accounts],
  );
  const partyNameById = useMemo(() => new Map(parties.map((party) => [party.id, party.name])), [parties]);

  const listParams = useMemo(() => {
    const params: Parameters<typeof listAccrualPlans>[0] = {
      settlement_status: settlementStatus,
      include_filter_options: true,
    };
    if (filterPartyId) {
      params.party_ids = [Number(filterPartyId)];
    }
    if (filterTargetAccountId) {
      params.target_account_ids = [Number(filterTargetAccountId)];
    }
    if (filterBridgeAccountId) {
      params.bridge_account_ids = [Number(filterBridgeAccountId)];
    }
    if (filterFromDate) {
      params.from_date = filterFromDate;
    }
    if (filterToDate) {
      params.to_date = filterToDate;
    }
    if (filterName.trim()) {
      params.name = filterName.trim();
    }
    return params;
  }, [
    settlementStatus,
    filterPartyId,
    filterTargetAccountId,
    filterBridgeAccountId,
    filterFromDate,
    filterToDate,
    filterName,
  ]);

  const reloadList = useCallback(async () => {
    setListError(null);
    setListLoading(true);
    try {
      const body = await listAccrualPlans(listParams);
      setPlans(body.plans);
      if (body.filter_options) {
        setFilterPartyIds(body.filter_options.party_ids);
        setFilterTargetAccountIds(body.filter_options.target_account_ids);
        setFilterBridgeAccountIds(body.filter_options.bridge_account_ids);
      }
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load plans");
      setPlans([]);
    } finally {
      setListLoading(false);
    }
  }, [listParams]);

  useEffect(() => {
    void reloadList();
  }, [reloadList]);

  const canCreate = useMemo(() => previewRows.length > 0 && !creating, [previewRows, creating]);
  const targetAccountOptions = useMemo(
    () => accounts.filter((a) => (direction === "revenue" ? a.type === "revenue" : a.type === "expense")),
    [accounts, direction],
  );
  const bridgeAccountOptions = useMemo(
    () => accounts.filter((a) => (direction === "revenue" ? a.type === "asset" : a.type === "liability")),
    [accounts, direction],
  );

  function partyFilterOptions(): Party[] {
    const ids = new Set(filterPartyIds);
    return parties.filter((p) => ids.has(p.id)).sort((a, b) => a.name.localeCompare(b.name));
  }

  function accountFilterOptions(ids: number[]): Account[] {
    const idSet = new Set(ids);
    return accounts.filter((a) => idSet.has(a.id)).sort((a, b) => a.name.localeCompare(b.name));
  }

  function validateForm(): string | null {
    if (!name.trim()) {
      return "Enter a plan name.";
    }
    if (!partyId) {
      return "Select a party.";
    }
    if (!targetAccountId) {
      return "Select a target account.";
    }
    if (!bridgeAccountId) {
      return "Select a bridge account.";
    }
    if (!summaryTemplate.trim()) {
      return "Enter a summary template.";
    }
    return null;
  }

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
    const formError = validateForm();
    if (formError) {
      setSubmitError(formError);
      setPreviewRows([]);
      return;
    }
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
    const formError = validateForm();
    if (formError) {
      setSubmitError(formError);
      return;
    }
    const guardrailError = validateAccountGuardrail();
    if (guardrailError) {
      setSubmitError(guardrailError);
      return;
    }
    setCreating(true);
    try {
      await createAccrualPlan(buildPayload());
      setPreviewRows([]);
      setName("");
      await reloadList();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create plan");
    } finally {
      setCreating(false);
    }
  }

  function formatAmount(value: string): string {
    const n = Number.parseFloat(value);
    if (!Number.isFinite(n)) {
      return value;
    }
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);
  }

  return (
    <>
      <section className="card journal-card-wide">
        <div className="cheque-register-toolbar">
          <h2>Accrual plans</h2>
          <div className="cheque-register-actions">
            <TableRowIconButton
              type="button"
              aria-label="Refresh list"
              title="Refresh list"
              disabled={listLoading}
              onClick={() => void reloadList()}
            >
              <RefreshCcw size={18} strokeWidth={2} aria-hidden />
            </TableRowIconButton>
            <TableRowIconButton
              type="button"
              aria-label="New accrual plan"
              title="Create plan (coming soon)"
              disabled
            >
              <FilePlus2 size={18} strokeWidth={2} aria-hidden />
            </TableRowIconButton>
          </div>
        </div>
        <p className="muted">
          Filter by settlement bucket, party, accounts, date range, or name. Row actions for view and edit arrive in
          follow-on tickets.
        </p>

        <div className="cheque-register-filters">
          <label>
            Settlement
            <select
              value={settlementStatus}
              onChange={(e) => setSettlementStatus(e.target.value as AccrualPlanSettlementStatus)}
              aria-label="Filter accrual plans by settlement status"
            >
              {SETTLEMENT_STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Party
            <select
              value={filterPartyId}
              onChange={(e) => setFilterPartyId(e.target.value)}
              aria-label="Filter accrual plans by party"
            >
              <option value="">All parties</option>
              {partyFilterOptions().map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Target account
            <select
              value={filterTargetAccountId}
              onChange={(e) => setFilterTargetAccountId(e.target.value)}
              aria-label="Filter accrual plans by target account"
            >
              <option value="">All target accounts</option>
              {accountFilterOptions(filterTargetAccountIds).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Bridge account
            <select
              value={filterBridgeAccountId}
              onChange={(e) => setFilterBridgeAccountId(e.target.value)}
              aria-label="Filter accrual plans by bridge account"
            >
              <option value="">All bridge accounts</option>
              {accountFilterOptions(filterBridgeAccountIds).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Name
            <input
              type="search"
              value={filterName}
              onChange={(e) => setFilterName(e.target.value)}
              aria-label="Filter accrual plans by name"
              placeholder="Regex on plan name"
            />
          </label>
          <label>
            From date
            <input
              type="date"
              value={filterFromDate}
              onChange={(e) => setFilterFromDate(e.target.value)}
              aria-label="Filter accrual plans from date"
            />
          </label>
          <label>
            To date
            <input
              type="date"
              value={filterToDate}
              onChange={(e) => setFilterToDate(e.target.value)}
              aria-label="Filter accrual plans to date"
            />
          </label>
        </div>

        {listError && <p className="error-text">{listError}</p>}

        <div style={{ overflowX: "auto" }}>
          <table aria-label="Accrual plans register">
            <thead>
              <tr>
                <th>Name</th>
                <th>Party</th>
                <th>Target</th>
                <th>Bridge</th>
                <th>Range</th>
                <th>Amount</th>
                <th>Direction</th>
                <th>Frequency</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {listLoading && plans.length === 0 ? (
                <tr>
                  <td colSpan={9} className="muted">
                    Loading…
                  </td>
                </tr>
              ) : plans.length === 0 ? (
                <tr>
                  <td colSpan={9} className="muted">
                    No plans for this filter.
                  </td>
                </tr>
              ) : (
                plans.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>{partyNameById.get(p.party_id) ?? `#${p.party_id}`}</td>
                    <td>{accountNameById.get(p.target_account_id) ?? `#${p.target_account_id}`}</td>
                    <td>{accountNameById.get(p.bridge_account_id) ?? `#${p.bridge_account_id}`}</td>
                    <td>
                      {p.start_date} – {p.end_date}
                    </td>
                    <td>{formatAmount(p.amount)}</td>
                    <td>{p.direction}</td>
                    <td>{p.frequency}</td>
                    <td aria-label="Plan actions reserved" />
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card journal-card-wide">
        <h2>Create accrual plan</h2>
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
              aria-label="Plan target account"
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
              aria-label="Plan bridge account"
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
                const rowAmount = debitLines.reduce((acc, line) => acc + line.amountNumber, 0);
                const partyNames = Array.from(
                  new Set(
                    row.lines
                      .map((line) => (line.party_id ? partyNameById.get(line.party_id) : null))
                      .filter((n): n is string => Boolean(n)),
                  ),
                );
                return (
                  <tr key={`${row.entry_date}-${idx}`}>
                    <td>{row.entry_date}</td>
                    <td>{row.summary}</td>
                    <td>{partyNames.length > 0 ? partyNames.join(", ") : "—"}</td>
                    <td>{debitLabel}</td>
                    <td>{creditLabel}</td>
                    <td className="journal-list-amount">{rowAmount.toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
