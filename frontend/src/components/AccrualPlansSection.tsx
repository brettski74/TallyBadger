import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Eye, FilePlus2, RefreshCcw } from "lucide-react";

import type { Account } from "../api/accounts";
import {
  createAccrualPlan,
  getAccrualPlanDetail,
  listAccrualPlans,
  previewAccrualPlan,
  type AccrualDirection,
  type AccrualFrequency,
  type AccrualPlan,
  type AccrualPlanDetailResponse,
  type AccrualPlanSettlementStatus,
  type AccrualPlanSummaryRollups,
  type AccrualPlanWrite,
  type AccrualObligation,
  type AccrualPreviewItem,
} from "../api/accrualPlans";
import type { Party } from "../api/parties";
import { useFormSaveDiscardShortcuts } from "../hooks/useFormSaveDiscardShortcuts";
import {
  discardActionTooltip,
  discardAriaKeyShortcuts,
  saveActionTooltip,
  saveAriaKeyShortcuts,
} from "../lib/keyboardHints";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";
import { JournalFilterMultiDropdown } from "./JournalFilterMultiDropdown";
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
  const [selectedPartyIds, setSelectedPartyIds] = useState<number[]>([]);
  const [selectedTargetAccountIds, setSelectedTargetAccountIds] = useState<number[]>([]);
  const [selectedBridgeAccountIds, setSelectedBridgeAccountIds] = useState<number[]>([]);
  const [filterName, setFilterName] = useState("");
  const [filterFromDate, setFilterFromDate] = useState("");
  const [filterToDate, setFilterToDate] = useState("");

  const [filterPartyIds, setFilterPartyIds] = useState<number[]>([]);
  const [filterTargetAccountIds, setFilterTargetAccountIds] = useState<number[]>([]);
  const [filterBridgeAccountIds, setFilterBridgeAccountIds] = useState<number[]>([]);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createDialogView, setCreateDialogView] = useState<"form" | "preview">("form");
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [viewPlanId, setViewPlanId] = useState<number | null>(null);
  const [viewDetail, setViewDetail] = useState<AccrualPlanDetailResponse | null>(null);
  const [viewLoading, setViewLoading] = useState(false);
  const [viewError, setViewError] = useState<string | null>(null);
  const createDialogRef = useRef<HTMLDialogElement>(null);
  const viewDialogRef = useRef<HTMLDialogElement>(null);
  const createFormRef = useRef<HTMLFormElement>(null);
  const editFormRef = useRef<HTMLFormElement>(null);
  const isMac = useMemo(() => isMacLikeUserAgent(), []);

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
    if (selectedPartyIds.length > 0) {
      params.party_ids = selectedPartyIds;
    }
    if (selectedTargetAccountIds.length > 0) {
      params.target_account_ids = selectedTargetAccountIds;
    }
    if (selectedBridgeAccountIds.length > 0) {
      params.bridge_account_ids = selectedBridgeAccountIds;
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
    selectedPartyIds,
    selectedTargetAccountIds,
    selectedBridgeAccountIds,
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

  useEffect(() => {
    if (!createDialogOpen) {
      return;
    }
    const el = createDialogRef.current;
    if (el && !el.open) {
      el.showModal();
    }
  }, [createDialogOpen]);

  useEffect(() => {
    if (!viewDialogOpen) {
      return;
    }
    const el = viewDialogRef.current;
    if (el && !el.open) {
      el.showModal();
    }
  }, [viewDialogOpen]);

  useEffect(() => {
    if (!viewDialogOpen || viewPlanId === null) {
      return;
    }
    let cancelled = false;
    setViewLoading(true);
    setViewError(null);
    setViewDetail(null);
    void getAccrualPlanDetail(viewPlanId)
      .then((detail) => {
        if (!cancelled) {
          setViewDetail(detail);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setViewError(err instanceof Error ? err.message : "Failed to load plan detail");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setViewLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [viewDialogOpen, viewPlanId]);

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

  function clearCreateForm() {
    setName("");
    setDirection("revenue");
    setPartyId("");
    setTargetAccountId("");
    setBridgeAccountId("");
    setFrequency("monthly_day");
    setDayOfWeek("0");
    setDayOfMonth("1");
    setMonthOfYear("1");
    const today = new Date().toISOString().slice(0, 10);
    setStartDate(today);
    setEndDate(today);
    setAmount("0.00");
    setSummaryTemplate("{plan} {month}");
    setDescriptionTemplate("");
    setBusinessDayAdjust(false);
    setPreviewRows([]);
    setSubmitError(null);
  }

  function closeCreateDialog() {
    setCreateDialogOpen(false);
    setCreateDialogView("form");
    setPreviewing(false);
    setCreating(false);
    clearCreateForm();
  }

  function openViewPlan(plan: AccrualPlan) {
    setViewPlanId(plan.id);
    setViewDetail(null);
    setViewError(null);
    setViewLoading(true);
    setViewDialogOpen(true);
  }

  function closeViewDialog() {
    setViewDialogOpen(false);
    setViewPlanId(null);
    setViewDetail(null);
    setViewError(null);
    setViewLoading(false);
  }

  function dayOfWeekLabel(value: number | null): string {
    if (value === null) {
      return "—";
    }
    return DAY_OPTIONS.find((d) => d.value === value)?.label ?? String(value);
  }

  function frequencyScheduleLabel(plan: AccrualPlan): string {
    if (plan.frequency === "weekly") {
      return `weekly (${dayOfWeekLabel(plan.day_of_week)})`;
    }
    if (plan.frequency === "monthly_day") {
      return `monthly (day ${plan.day_of_month ?? "—"})`;
    }
    return `yearly (${plan.day_of_month ?? "—"}/${plan.month_of_year ?? "—"})`;
  }

  function handleNewPlan() {
    clearCreateForm();
    setCreateDialogView("form");
    setCreateDialogOpen(true);
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

  async function handleShowPreview() {
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
      setCreateDialogView("preview");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to preview plan");
      setPreviewRows([]);
    } finally {
      setPreviewing(false);
    }
  }

  async function handleCreatePlan() {
    setSubmitError(null);
    if (previewRows.length === 0) {
      setSubmitError("Preview entries before saving the plan.");
      return;
    }
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
      closeCreateDialog();
      await reloadList();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create plan");
    } finally {
      setCreating(false);
    }
  }

  async function handleDialogSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createDialogView === "preview") {
      await handleCreatePlan();
    }
  }

  function returnToCreateForm() {
    setCreateDialogView("form");
    setSubmitError(null);
  }

  const canSubmitCreate = useMemo(() => {
    if (!createDialogOpen) {
      return false;
    }
    if (createDialogView === "preview") {
      return previewRows.length > 0 && !creating;
    }
    return !previewing;
  }, [createDialogOpen, createDialogView, previewRows.length, creating, previewing]);

  useFormSaveDiscardShortcuts({
    createFormRef,
    editFormRef,
    editingId: null,
    createDialogActive: createDialogOpen,
    canSubmitCreate,
    canSubmitEdit: false,
    createSubmitting: previewing || creating,
    editSubmitting: false,
    requestCreateSubmit: () => {
      if (createDialogView === "preview") {
        createFormRef.current?.requestSubmit();
      } else {
        void handleShowPreview();
      }
    },
    requestEditSubmit: () => undefined,
    requestEditDiscard: () => undefined,
    requestCreateDiscard: closeCreateDialog,
  });

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

  function renderPreviewTable() {
    if (previewRows.length === 0) {
      return <p className="muted">No preview rows.</p>;
    }
    return (
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
    );
  }

  function renderDayOfWeekMonthField() {
    if (frequency === "weekly") {
      return (
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
      );
    }
    if (frequency === "monthly_day") {
      return (
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
      );
    }
    return (
      <label>
        Day/Month:
        <span className="accrual-day-month-inline">
          <input
            aria-label="Day of month"
            type="number"
            min={1}
            max={31}
            value={dayOfMonth}
            onChange={(e) => setDayOfMonth(e.target.value)}
          />
          <span className="accrual-day-month-separator" aria-hidden>
            /
          </span>
          <input
            aria-label="Month of year"
            type="number"
            min={1}
            max={12}
            value={monthOfYear}
            onChange={(e) => setMonthOfYear(e.target.value)}
          />
        </span>
      </label>
    );
  }

  function renderCreateFormFields() {
    return (
      <div className="cheque-form-grid">
        <div className="cheque-form-col">
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
        </div>
        <div className="cheque-form-col">
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
          {renderDayOfWeekMonthField()}
          <label>
            Start date
            <input
              aria-label="Plan start date"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label>
            End date
            <input
              aria-label="Plan end date"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
          <label>
            Amount
            <input aria-label="Plan amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className={`checkbox${frequency === "weekly" ? " accrual-form-field-disabled" : ""}`}>
            <input
              aria-label="Business day adjust"
              type="checkbox"
              checked={businessDayAdjust}
              disabled={frequency === "weekly"}
              onChange={(e) => setBusinessDayAdjust(e.target.checked)}
            />
            Roll weekends to Monday
          </label>
        </div>
        <label className="cheque-form-summary">
          Summary template
          <input
            aria-label="Summary template"
            value={summaryTemplate}
            onChange={(e) => setSummaryTemplate(e.target.value)}
          />
        </label>
        <label className="cheque-form-summary">
          Description template
          <input
            aria-label="Description template"
            value={descriptionTemplate}
            onChange={(e) => setDescriptionTemplate(e.target.value)}
          />
        </label>
      </div>
    );
  }

  function viewFrequencyLabel(plan: AccrualPlan): string {
    const schedule = frequencyScheduleLabel(plan);
    return plan.business_day_adjust ? `${schedule} (roll forward)` : schedule;
  }

  function renderViewPlanFields(plan: AccrualPlan) {
    return (
      <div className="cheque-form-grid accrual-view-plan-fields">
        <div className="cheque-form-col">
          <p>
            <strong>Plan name</strong>
            <br />
            {plan.name}
          </p>
          <p>
            <strong>Direction</strong>
            <br />
            {plan.direction}
          </p>
          <p>
            <strong>Party</strong>
            <br />
            {partyNameById.get(plan.party_id) ?? `#${plan.party_id}`}
          </p>
        </div>
        <div className="cheque-form-col">
          <p>
            <strong>Target account</strong>
            <br />
            {accountNameById.get(plan.target_account_id) ?? `#${plan.target_account_id}`}
          </p>
          <p>
            <strong>Bridge account</strong>
            <br />
            {accountNameById.get(plan.bridge_account_id) ?? `#${plan.bridge_account_id}`}
          </p>
          <p>
            <strong>Amount</strong>
            <br />
            {formatAmount(plan.amount)}
          </p>
        </div>
        <div className="cheque-form-col">
          <p>
            <strong>Frequency</strong>
            <br />
            {viewFrequencyLabel(plan)}
          </p>
          <p>
            <strong>Start date</strong>
            <br />
            {plan.start_date}
          </p>
          <p>
            <strong>End date</strong>
            <br />
            {plan.end_date}
          </p>
        </div>
        <hr className="accrual-view-fields-divider" />
        <p className="cheque-form-summary">
          <strong>Summary template</strong>
          <br />
          {plan.summary_template}
        </p>
        <p className="cheque-form-summary">
          <strong>Description template</strong>
          <br />
          {plan.description_template?.trim() ? plan.description_template : "—"}
        </p>
      </div>
    );
  }

  function renderSummaryRollups(summary: AccrualPlanSummaryRollups) {
    const items: { label: string; value: string }[] = [
      { label: "Total original accrued", value: formatAmount(summary.total_original_accrued) },
      { label: "Total settled to date", value: formatAmount(summary.total_settled_to_date) },
      { label: "Past due", value: formatAmount(summary.past_due) },
      { label: "Not yet due", value: formatAmount(summary.not_yet_due) },
      { label: "Unearned", value: formatAmount(summary.unearned) },
    ];
    return (
      <dl className="accrual-plan-summary-rollups" aria-label="Plan summary rollups">
        {items.map((item) => (
          <div key={item.label} className="accrual-plan-summary-rollup">
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
      </dl>
    );
  }

  function renderObligationsTable(obligations: AccrualObligation[]) {
    if (obligations.length === 0) {
      return <p className="muted">No obligations on this plan.</p>;
    }
    return (
      <table className="journal-entry-list accrual-view-obligations-table" aria-label="Plan obligations">
        <thead>
          <tr>
            <th>Accrual date</th>
            <th>Original</th>
            <th>Open</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {obligations.map((ob) => (
            <tr key={ob.id}>
              <td>{ob.source_entry_date ?? "—"}</td>
              <td>{formatAmount(ob.original_amount)}</td>
              <td>{formatAmount(ob.open_amount)}</td>
              <td>{ob.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
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
              title="New accrual plan"
              onClick={handleNewPlan}
            >
              <FilePlus2 size={18} strokeWidth={2} aria-hidden />
            </TableRowIconButton>
          </div>
        </div>
        <p className="muted">Filter by settlement bucket, party, accounts, date range, or name.</p>

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
          <JournalFilterMultiDropdown
            label="Party"
            ariaFilterLabel="Filter accrual plans by party"
            options={partyFilterOptions().map((p) => ({ id: p.id, name: p.name }))}
            selectedIds={selectedPartyIds}
            onIdsChange={setSelectedPartyIds}
          />
          <JournalFilterMultiDropdown
            label="Target account"
            ariaFilterLabel="Filter accrual plans by target account"
            options={accountFilterOptions(filterTargetAccountIds).map((a) => ({
              id: a.id,
              name: a.name,
            }))}
            selectedIds={selectedTargetAccountIds}
            onIdsChange={setSelectedTargetAccountIds}
          />
          <JournalFilterMultiDropdown
            label="Bridge account"
            ariaFilterLabel="Filter accrual plans by bridge account"
            options={accountFilterOptions(filterBridgeAccountIds).map((a) => ({
              id: a.id,
              name: a.name,
            }))}
            selectedIds={selectedBridgeAccountIds}
            onIdsChange={setSelectedBridgeAccountIds}
          />
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
                    <td>
                      <div className="table-row-actions">
                        {p.has_settlement_allocations ? (
                          <TableRowIconButton
                            type="button"
                            aria-label={`View plan ${p.name}`}
                            title="View plan"
                            onClick={() => openViewPlan(p)}
                          >
                            <Eye size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {createDialogOpen && (
        <dialog
          ref={createDialogRef}
          className={createDialogView === "preview" ? "cheque-dialog cheque-dialog-preview" : "cheque-dialog"}
          aria-labelledby="accrual-create-dialog-title"
          onClose={closeCreateDialog}
        >
          <form
            ref={createFormRef}
            method="dialog"
            className="cheque-dialog-inner"
            noValidate
            onSubmit={(e) => void handleDialogSubmit(e)}
          >
            <div className="cheque-dialog-header">
              <h2 id="accrual-create-dialog-title">
                {createDialogView === "preview" ? "Preview accrual entries" : "New accrual plan"}
              </h2>
              <button type="button" className="button-secondary" onClick={closeCreateDialog}>
                Close
              </button>
            </div>

            {createDialogView === "form" ? (
              <>
                <p className="muted">Preview generated accrual entries, then commit plan and entries together.</p>
                {renderCreateFormFields()}
                {submitError && (
                  <p className="error" role="alert">
                    {submitError}
                  </p>
                )}
                <div className="dialog-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={closeCreateDialog}
                    title={discardActionTooltip(isMac)}
                    aria-label={discardActionTooltip(isMac)}
                    aria-keyshortcuts={discardAriaKeyShortcuts(isMac)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={previewing}
                    onClick={() => void handleShowPreview()}
                    title={saveActionTooltip(isMac)}
                    aria-label={isMac ? "Preview entries (⌘+S)" : "Preview entries (Ctrl+S)"}
                    aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
                  >
                    {previewing ? "Previewing…" : "Preview entries"}
                  </button>
                </div>
              </>
            ) : (
              <>
                {renderPreviewTable()}
                {submitError && (
                  <p className="error" role="alert">
                    {submitError}
                  </p>
                )}
                <div className="dialog-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={returnToCreateForm}
                    aria-label="Cancel"
                  >
                    Cancel
                  </button>
                  <button type="button" className="button-secondary" onClick={returnToCreateForm} aria-label="Edit">
                    Edit
                  </button>
                  <button
                    type="submit"
                    disabled={creating || previewRows.length === 0}
                    title={saveActionTooltip(isMac)}
                    aria-label={isMac ? "Create plan (⌘+S)" : "Create plan (Ctrl+S)"}
                    aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
                  >
                    {creating ? "Creating…" : "Create plan"}
                  </button>
                </div>
              </>
            )}
          </form>
        </dialog>
      )}

      {viewDialogOpen && (
        <dialog
          ref={viewDialogRef}
          className="cheque-dialog accrual-view-dialog"
          aria-labelledby="accrual-view-dialog-title"
          onClose={closeViewDialog}
        >
          <div className="cheque-dialog-inner">
            <div className="cheque-dialog-header">
              <h2 id="accrual-view-dialog-title">
                {viewDetail?.plan.name ?? (viewLoading ? "Loading plan…" : "View accrual plan")}
              </h2>
              <button type="button" className="button-secondary" onClick={closeViewDialog}>
                Close
              </button>
            </div>

            {viewLoading && <p className="muted">Loading plan detail…</p>}
            {viewError && (
              <p className="error" role="alert">
                {viewError}
              </p>
            )}
            {viewDetail && !viewLoading && (
              <>
                {renderViewPlanFields(viewDetail.plan)}
                {renderSummaryRollups(viewDetail.summary)}
                {renderObligationsTable(viewDetail.obligations)}
              </>
            )}
          </div>
        </dialog>
      )}
    </>
  );
}
