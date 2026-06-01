import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookCopy, Eye, FilePlus2, Pencil, RefreshCcw, Trash2 } from "lucide-react";

import type { Account } from "../api/accounts";
import {
  cancelAccrualPlan,
  createAccrualPlan,
  getAccrualPlanDetail,
  listAccrualPlans,
  previewAccrualPlan,
  updateAccrualPlan,
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
import { useAccrualPlanModalShortcuts } from "../hooks/useAccrualPlanModalShortcuts";
import {
  proposeDuplicateAccrualPlanName,
  shiftAccrualPlanDatesByOneYear,
} from "../lib/accrualPlanDuplicate";
import {
  newActionTooltip,
  newAriaKeyShortcuts,
  newEntityAriaLabel,
  previewReturnToFormActionTooltip,
  previewReturnToFormAriaKeyShortcuts,
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

type AccrualPlanCreateFormSnapshot = {
  name: string;
  direction: AccrualDirection;
  partyId: string;
  targetAccountId: string;
  bridgeAccountId: string;
  frequency: AccrualFrequency;
  dayOfWeek: string;
  dayOfMonth: string;
  monthOfYear: string;
  startDate: string;
  endDate: string;
  amount: string;
  summaryTemplate: string;
  descriptionTemplate: string;
  businessDayAdjust: boolean;
};

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
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editDialogView, setEditDialogView] = useState<"form" | "preview">("form");
  const [editingPlanId, setEditingPlanId] = useState<number | null>(null);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [viewPlanId, setViewPlanId] = useState<number | null>(null);
  const [viewDetail, setViewDetail] = useState<AccrualPlanDetailResponse | null>(null);
  const [viewLoading, setViewLoading] = useState(false);
  const [viewError, setViewError] = useState<string | null>(null);
  const createDialogRef = useRef<HTMLDialogElement>(null);
  const editDialogRef = useRef<HTMLDialogElement>(null);
  const viewDialogRef = useRef<HTMLDialogElement>(null);
  const createFormRef = useRef<HTMLFormElement>(null);
  const editFormRef = useRef<HTMLFormElement>(null);
  const createFormBaselineRef = useRef<AccrualPlanCreateFormSnapshot | null>(null);
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
  const [editing, setEditing] = useState(false);
  const [cancellingPlanId, setCancellingPlanId] = useState<number | null>(null);

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
    if (!editDialogOpen) {
      return;
    }
    const el = editDialogRef.current;
    if (el && !el.open) {
      el.showModal();
    }
  }, [editDialogOpen]);

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

  function defaultCreateFormSnapshot(): AccrualPlanCreateFormSnapshot {
    const today = new Date().toISOString().slice(0, 10);
    return {
      name: "",
      direction: "revenue",
      partyId: "",
      targetAccountId: "",
      bridgeAccountId: "",
      frequency: "monthly_day",
      dayOfWeek: "0",
      dayOfMonth: "1",
      monthOfYear: "1",
      startDate: today,
      endDate: today,
      amount: "0.00",
      summaryTemplate: "{plan} {month}",
      descriptionTemplate: "",
      businessDayAdjust: false,
    };
  }

  function createFormSnapshotFromPlan(
    plan: AccrualPlan,
    overrides: Partial<Pick<AccrualPlanCreateFormSnapshot, "name" | "startDate" | "endDate">> = {},
  ): AccrualPlanCreateFormSnapshot {
    return {
      name: overrides.name ?? plan.name,
      direction: plan.direction,
      partyId: String(plan.party_id),
      targetAccountId: String(plan.target_account_id),
      bridgeAccountId: String(plan.bridge_account_id),
      frequency: plan.frequency,
      dayOfWeek: plan.day_of_week != null ? String(plan.day_of_week) : "0",
      dayOfMonth: plan.day_of_month != null ? String(plan.day_of_month) : "1",
      monthOfYear: plan.month_of_year != null ? String(plan.month_of_year) : "1",
      startDate: overrides.startDate ?? plan.start_date,
      endDate: overrides.endDate ?? plan.end_date,
      amount: plan.amount,
      summaryTemplate: plan.summary_template,
      descriptionTemplate: plan.description_template ?? "",
      businessDayAdjust: plan.business_day_adjust,
    };
  }

  function clearPlanForm() {
    applyCreateFormSnapshot(defaultCreateFormSnapshot());
  }

  function applyCreateFormSnapshot(snapshot: AccrualPlanCreateFormSnapshot): void {
    setName(snapshot.name);
    setDirection(snapshot.direction);
    setPartyId(snapshot.partyId);
    setTargetAccountId(snapshot.targetAccountId);
    setBridgeAccountId(snapshot.bridgeAccountId);
    setFrequency(snapshot.frequency);
    setDayOfWeek(snapshot.dayOfWeek);
    setDayOfMonth(snapshot.dayOfMonth);
    setMonthOfYear(snapshot.monthOfYear);
    setStartDate(snapshot.startDate);
    setEndDate(snapshot.endDate);
    setAmount(snapshot.amount);
    setSummaryTemplate(snapshot.summaryTemplate);
    setDescriptionTemplate(snapshot.descriptionTemplate);
    setBusinessDayAdjust(snapshot.businessDayAdjust);
    setPreviewRows([]);
    setSubmitError(null);
  }

  function restoreCreateFormBaseline(): void {
    const baseline = createFormBaselineRef.current;
    if (!baseline) {
      clearPlanForm();
      return;
    }
    applyCreateFormSnapshot(baseline);
    setCreateDialogView("form");
  }

  function loadPlanIntoForm(plan: AccrualPlan) {
    setName(plan.name);
    setDirection(plan.direction);
    setPartyId(String(plan.party_id));
    setTargetAccountId(String(plan.target_account_id));
    setBridgeAccountId(String(plan.bridge_account_id));
    setFrequency(plan.frequency);
    setDayOfWeek(plan.day_of_week != null ? String(plan.day_of_week) : "0");
    setDayOfMonth(plan.day_of_month != null ? String(plan.day_of_month) : "1");
    setMonthOfYear(plan.month_of_year != null ? String(plan.month_of_year) : "1");
    setStartDate(plan.start_date);
    setEndDate(plan.end_date);
    setAmount(plan.amount);
    setSummaryTemplate(plan.summary_template);
    setDescriptionTemplate(plan.description_template ?? "");
    setBusinessDayAdjust(plan.business_day_adjust);
    setPreviewRows([]);
    setSubmitError(null);
  }

  function closeCreateDialog() {
    setCreateDialogOpen(false);
    setCreateDialogView("form");
    setPreviewing(false);
    setCreating(false);
    createFormBaselineRef.current = null;
    clearPlanForm();
  }

  function closeEditDialog() {
    setEditDialogOpen(false);
    setEditDialogView("form");
    setEditingPlanId(null);
    setPreviewing(false);
    setEditing(false);
    clearPlanForm();
  }

  function isUnsettledPlan(plan: AccrualPlan): boolean {
    return !plan.has_settlement_allocations;
  }

  function openEditPlan(plan: AccrualPlan) {
    loadPlanIntoForm(plan);
    setEditingPlanId(plan.id);
    setEditDialogView("form");
    setEditDialogOpen(true);
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
    const baseline = defaultCreateFormSnapshot();
    applyCreateFormSnapshot(baseline);
    createFormBaselineRef.current = baseline;
    setCreateDialogView("form");
    setCreateDialogOpen(true);
  }

  async function openDuplicatePlan(plan: AccrualPlan) {
    setListError(null);
    try {
      const body = await listAccrualPlans({ settlement_status: "any" });
      const existingNames = body.plans.map((p) => p.name);
      const proposedName = proposeDuplicateAccrualPlanName(plan.name, existingNames);
      const dates = shiftAccrualPlanDatesByOneYear(plan.start_date, plan.end_date);
      const baseline = createFormSnapshotFromPlan(plan, {
        name: proposedName,
        startDate: dates.start,
        endDate: dates.end,
      });
      applyCreateFormSnapshot(baseline);
      createFormBaselineRef.current = baseline;
      setCreateDialogView("form");
      setCreateDialogOpen(true);
    } catch (err) {
      setListError(err instanceof Error ? err.message : `Failed to duplicate plan "${plan.name}"`);
    }
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
      if (editDialogOpen) {
        setEditDialogView("preview");
      } else {
        setCreateDialogView("preview");
      }
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

  async function handleUpdatePlan() {
    if (editingPlanId === null) {
      return;
    }
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
    setEditing(true);
    try {
      await updateAccrualPlan(editingPlanId, buildPayload());
      closeEditDialog();
      await reloadList();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to update plan");
    } finally {
      setEditing(false);
    }
  }

  async function handleCancelPlan(plan: AccrualPlan) {
    const confirmed = window.confirm(
      `Cancel accrual plan "${plan.name}"? This removes the plan and its accrual journal entries.`,
    );
    if (!confirmed) {
      return;
    }
    setListError(null);
    setCancellingPlanId(plan.id);
    try {
      await cancelAccrualPlan(plan.id);
      await reloadList();
    } catch (err) {
      setListError(err instanceof Error ? err.message : `Failed to cancel plan "${plan.name}"`);
    } finally {
      setCancellingPlanId(null);
    }
  }

  async function handleCreateDialogSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createDialogView === "preview") {
      await handleCreatePlan();
    }
  }

  async function handleEditDialogSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editDialogView === "preview") {
      await handleUpdatePlan();
    }
  }

  function returnToCreateForm() {
    setCreateDialogView("form");
    setSubmitError(null);
  }

  function returnToEditForm() {
    setEditDialogView("form");
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

  const canSubmitEdit = useMemo(() => {
    if (!editDialogOpen || editingPlanId === null) {
      return false;
    }
    if (editDialogView === "preview") {
      return previewRows.length > 0 && !editing;
    }
    return !previewing;
  }, [editDialogOpen, editDialogView, editingPlanId, previewRows.length, editing, previewing]);

  useAccrualPlanModalShortcuts({
    createDialogOpen,
    createDialogView,
    editDialogOpen,
    editDialogView,
    viewDialogOpen,
    canSubmitCreate,
    canSubmitEdit,
    createSubmitting: previewing || creating,
    editSubmitting: previewing || editing,
    onCreateSave: () => {
      if (createDialogView === "preview") {
        createFormRef.current?.requestSubmit();
      } else {
        void handleShowPreview();
      }
    },
    onEditSave: () => {
      if (editDialogView === "preview") {
        editFormRef.current?.requestSubmit();
      } else {
        void handleShowPreview();
      }
    },
    onCreateClose: closeCreateDialog,
    onEditClose: closeEditDialog,
    onViewClose: closeViewDialog,
    onCreateReturnToForm: returnToCreateForm,
    onEditReturnToForm: returnToEditForm,
    onCreateRevertForm: restoreCreateFormBaseline,
    onNewPlan: handleNewPlan,
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

  function renderSummaryRollups(summary: AccrualPlanSummaryRollups, direction: AccrualPlan["direction"]) {
    const settledEarlyLabel = direction === "revenue" ? "Unearned" : "Prepaid";
    const settledEarlyValue =
      direction === "revenue" ? summary.unearned : summary.prepaid;
    const items: { label: string; value: string }[] = [
      { label: "Total original accrued", value: formatAmount(summary.total_original_accrued) },
      { label: "Total settled to date", value: formatAmount(summary.total_settled_to_date) },
      { label: "Past due", value: formatAmount(summary.past_due) },
      { label: "Not yet due", value: formatAmount(summary.not_yet_due) },
      { label: settledEarlyLabel, value: formatAmount(settledEarlyValue) },
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
              aria-label={newEntityAriaLabel("New accrual plan", isMac)}
              title={newActionTooltip(isMac)}
              aria-keyshortcuts={newAriaKeyShortcuts(isMac)}
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
                        {isUnsettledPlan(p) ? (
                          <>
                            <TableRowIconButton
                              type="button"
                              aria-label={`Edit plan ${p.name}`}
                              title="Edit plan"
                              onClick={() => openEditPlan(p)}
                            >
                              <Pencil size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                            <TableRowIconButton
                              type="button"
                              aria-label={`Duplicate plan ${p.name}`}
                              title="Duplicate plan"
                              onClick={() => void openDuplicatePlan(p)}
                            >
                              <BookCopy size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                            <TableRowIconButton
                              type="button"
                              aria-label={`Cancel plan ${p.name}`}
                              title="Cancel plan"
                              disabled={cancellingPlanId === p.id}
                              onClick={() => void handleCancelPlan(p)}
                            >
                              <Trash2 size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                          </>
                        ) : (
                          <>
                            <TableRowIconButton
                              type="button"
                              aria-label={`View plan ${p.name}`}
                              title="View plan"
                              onClick={() => openViewPlan(p)}
                            >
                              <Eye size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                            <TableRowIconButton
                              type="button"
                              aria-label={`Duplicate plan ${p.name}`}
                              title="Duplicate plan"
                              onClick={() => void openDuplicatePlan(p)}
                            >
                              <BookCopy size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                          </>
                        )}
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
            onSubmit={(e) => void handleCreateDialogSubmit(e)}
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
                    aria-label="Close"
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
                    aria-label="Close"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={returnToCreateForm}
                    title={previewReturnToFormActionTooltip(isMac)}
                    aria-label={previewReturnToFormActionTooltip(isMac)}
                    aria-keyshortcuts={previewReturnToFormAriaKeyShortcuts(isMac)}
                  >
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

      {editDialogOpen && (
        <dialog
          ref={editDialogRef}
          className={editDialogView === "preview" ? "cheque-dialog cheque-dialog-preview" : "cheque-dialog"}
          aria-labelledby="accrual-edit-dialog-title"
          onClose={closeEditDialog}
        >
          <form
            ref={editFormRef}
            method="dialog"
            className="cheque-dialog-inner"
            noValidate
            onSubmit={(e) => void handleEditDialogSubmit(e)}
          >
            <div className="cheque-dialog-header">
              <h2 id="accrual-edit-dialog-title">
                {editDialogView === "preview" ? "Preview accrual entries" : "Edit accrual plan"}
              </h2>
              <button type="button" className="button-secondary" onClick={closeEditDialog}>
                Close
              </button>
            </div>

            {editDialogView === "form" ? (
              <>
                <p className="muted">Preview generated accrual entries, then save changes to the plan and schedule.</p>
                {renderCreateFormFields()}
                {submitError && (
                  <p className="error" role="alert">
                    {submitError}
                  </p>
                )}
                <div className="dialog-actions">
                  <button type="button" className="button-secondary" onClick={closeEditDialog} aria-label="Close">
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
                    onClick={returnToEditForm}
                    aria-label="Close"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={returnToEditForm}
                    title={previewReturnToFormActionTooltip(isMac)}
                    aria-label={previewReturnToFormActionTooltip(isMac)}
                    aria-keyshortcuts={previewReturnToFormAriaKeyShortcuts(isMac)}
                  >
                    Edit
                  </button>
                  <button
                    type="submit"
                    disabled={editing || previewRows.length === 0}
                    title={saveActionTooltip(isMac)}
                    aria-label={isMac ? "Save plan (⌘+S)" : "Save plan (Ctrl+S)"}
                    aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
                  >
                    {editing ? "Saving…" : "Save plan"}
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
                {renderSummaryRollups(viewDetail.summary, viewDetail.plan.direction)}
                {renderObligationsTable(viewDetail.obligations)}
              </>
            )}
          </div>
        </dialog>
      )}
    </>
  );
}
