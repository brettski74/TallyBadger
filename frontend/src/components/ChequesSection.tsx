import { FormEvent, Fragment, MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ban, Eye, FilePlus2, Pencil, RefreshCcw, SquareCheck } from "lucide-react";

import type { Account } from "../api/accounts";
import { useChequeCreateModalShortcuts } from "../hooks/useChequeCreateModalShortcuts";
import {
  newActionTooltip,
  newAriaKeyShortcuts,
  newEntityAriaLabel,
  previewReturnToFormActionTooltip,
  previewReturnToFormAriaKeyShortcuts,
  discardActionTooltip,
  discardAriaKeyShortcuts,
  saveActionTooltip,
  saveAriaKeyShortcuts,
} from "../lib/keyboardHints";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";
import {
  type Cheque,
  type ChequeFilterOptions,
  type ChequeIncrementUnit,
  type ChequeListStatus,
  type ChequeSeriesCreateInput,
  type ChequeSeriesPreview,
  type ChequeSeriesPreviewRow,
  createCheque,
  createChequeSeries,
  listChequeFilterOptions,
  listCheques,
  patchCheque,
  previewChequeSeries,
} from "../api/cheques";
import type { Party } from "../api/parties";
import { type LedgerSettings, getLedgerSettings } from "../api/settlements";
import { ChequePartyFilterMultiDropdown, type ChequePartyFilterId } from "./ChequePartyFilterMultiDropdown";
import { JournalFilterMultiDropdown } from "./JournalFilterMultiDropdown";
import { TableRowIconButton } from "./TableRowIconButton";

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

function parseChequeAmount(value: string): string | null {
  const cleaned = value.replace(/[$,\s]/g, "");
  if (cleaned === "") {
    return null;
  }
  const n = Number.parseFloat(cleaned);
  if (!Number.isFinite(n)) {
    return null;
  }
  return n.toFixed(2);
}

function formatChequeCurrency(amount: string | number): string {
  const raw = typeof amount === "number" ? amount : Number.parseFloat(amount.replace(/[$,\s]/g, ""));
  if (!Number.isFinite(raw)) {
    return String(amount);
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(raw);
}

export function ChequesSection({ accounts, parties }: ChequesSectionProps) {
  const [listStatus, setListStatus] = useState<ChequeListStatus>("open");
  const [selectedPartyIds, setSelectedPartyIds] = useState<ChequePartyFilterId[]>([]);
  const [selectedCreditAccountIds, setSelectedCreditAccountIds] = useState<number[]>([]);
  const [selectedDebitAccountIds, setSelectedDebitAccountIds] = useState<number[]>([]);
  const [issueFromDate, setIssueFromDate] = useState("");
  const [issueToDate, setIssueToDate] = useState("");
  const [clearedFromDate, setClearedFromDate] = useState("");
  const [clearedToDate, setClearedToDate] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [summaryFilter, setSummaryFilter] = useState("");
  const [filterOptions, setFilterOptions] = useState<ChequeFilterOptions>({
    parties: [],
    credit_accounts: [],
    debit_accounts: [],
  });
  const [cheques, setCheques] = useState<Cheque[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);

  const [isCreating, setIsCreating] = useState(false);
  const [selected, setSelected] = useState<Cheque | null>(null);
  const [highlightedId, setHighlightedId] = useState<number | null>(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);

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
  const [maxChequeSeriesCount, setMaxChequeSeriesCount] = useState(60);

  const [seriesEnabled, setSeriesEnabled] = useState(false);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [incrementUnit, setIncrementUnit] = useState<ChequeIncrementUnit>("months");
  const [incrementN, setIncrementN] = useState("1");
  const [seriesStopMode, setSeriesStopMode] = useState<"count" | "end">("count");
  const [seriesCount, setSeriesCount] = useState("5");
  const [seriesEndDate, setSeriesEndDate] = useState("");
  const [seriesPreview, setSeriesPreview] = useState<ChequeSeriesPreview | null>(null);
  const [seriesPreviewLoading, setSeriesPreviewLoading] = useState(false);
  const [createDialogView, setCreateDialogView] = useState<"form" | "preview">("form");

  const createFormRef = useRef<HTMLFormElement>(null);
  const editFormRef = useRef<HTMLFormElement>(null);
  const createDialogRef = useRef<HTMLDialogElement>(null);
  const editDialogRef = useRef<HTMLDialogElement>(null);
  const viewDialogRef = useRef<HTMLDialogElement>(null);
  const createFormBaselineRef = useRef<{
    creditId: string;
    debitId: string;
    summary: string;
    chequeNumber: string;
    issueDate: string;
    amount: string;
    partyId: string;
    seriesEnabled: boolean;
    incrementUnit: ChequeIncrementUnit;
    incrementN: string;
    seriesStopMode: "count" | "end";
    seriesCount: string;
    seriesEndDate: string;
  } | null>(null);
  const editFormBaselineRef = useRef<{
    creditId: string;
    debitId: string;
    summary: string;
    chequeNumber: string;
    issueDate: string;
    amount: string;
    partyId: string;
  } | null>(null);
  const isMac = useMemo(() => isMacLikeUserAgent(), []);

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

  const listParams = useMemo(
    () => ({
      status: listStatus,
      party_ids: selectedPartyIds.length > 0 ? selectedPartyIds : undefined,
      credit_account_ids: selectedCreditAccountIds.length > 0 ? selectedCreditAccountIds : undefined,
      debit_account_ids: selectedDebitAccountIds.length > 0 ? selectedDebitAccountIds : undefined,
      issue_from_date: issueFromDate || undefined,
      issue_to_date: issueToDate || undefined,
      cleared_from_date: clearedFromDate || undefined,
      cleared_to_date: clearedToDate || undefined,
      min_amount: minAmount.trim() || undefined,
      max_amount: maxAmount.trim() || undefined,
      summary: summaryFilter.trim() || undefined,
    }),
    [
      listStatus,
      selectedPartyIds,
      selectedCreditAccountIds,
      selectedDebitAccountIds,
      issueFromDate,
      issueToDate,
      clearedFromDate,
      clearedToDate,
      minAmount,
      maxAmount,
      summaryFilter,
    ],
  );

  const reloadList = useCallback(async () => {
    setListError(null);
    setListLoading(true);
    try {
      const rows = await listCheques(listParams);
      setCheques(rows);
      setSelected((prev) => {
        if (!prev) {
          return null;
        }
        return rows.find((c) => c.id === prev.id) ?? null;
      });
      setHighlightedId((prev) => {
        if (prev == null) {
          return null;
        }
        return rows.some((c) => c.id === prev) ? prev : null;
      });
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load cheques");
      setCheques([]);
      setSelected(null);
    } finally {
      setListLoading(false);
    }
  }, [listParams]);

  useEffect(() => {
    void reloadList();
  }, [reloadList]);

  useEffect(() => {
    void listChequeFilterOptions()
      .then((body) => {
        setFilterOptions({
          parties: body.parties ?? [],
          credit_accounts: body.credit_accounts ?? [],
          debit_accounts: body.debit_accounts ?? [],
        });
      })
      .catch(() => {
        setFilterOptions({ parties: [], credit_accounts: [], debit_accounts: [] });
      });
  }, []);

  const refreshDefaults = useCallback(async () => {
    try {
      const settings: LedgerSettings = await getLedgerSettings();
      setDefaultCreditId(settings.default_cheque_credit_account_id);
      setDefaultDebitId(settings.default_cheque_debit_account_id);
      setMaxChequeSeriesCount(settings.max_cheque_series_count);
    } catch {
      // Defaults are an enhancement, not a hard dependency for the rest of the form.
      setDefaultCreditId(null);
      setDefaultDebitId(null);
    }
  }, []);

  useEffect(() => {
    void refreshDefaults();
  }, [refreshDefaults]);

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

  function captureEditFormBaselineFromCheque(ch: Cheque) {
    editFormBaselineRef.current = {
      creditId: String(ch.credit_account_id),
      debitId: String(ch.debit_account_id),
      summary: ch.summary,
      chequeNumber: String(ch.cheque_number),
      issueDate: ch.issue_date,
      amount: ch.amount,
      partyId: ch.party_id != null ? String(ch.party_id) : "",
    };
  }

  function restoreEditFormBaseline() {
    const baseline = editFormBaselineRef.current;
    if (!baseline || !selected) {
      return;
    }
    setCreditId(baseline.creditId);
    setDebitId(baseline.debitId);
    setSummary(baseline.summary);
    setChequeNumber(baseline.chequeNumber);
    setIssueDate(baseline.issueDate);
    setAmount(baseline.amount);
    setPartyId(baseline.partyId);
    setFormError(null);
  }

  function closeEditDialog() {
    setEditDialogOpen(false);
    setFormError(null);
    if (selected) {
      hydrateForm(selected);
    }
  }

  function closeViewDialog() {
    setViewDialogOpen(false);
    setFormError(null);
    if (selected) {
      hydrateForm(selected);
    }
  }

  function openEditCheque(ch: Cheque) {
    if (ch.status !== "open") {
      openViewCheque(ch);
      return;
    }
    if (createDialogOpen) {
      closeCreateDialog();
    }
    if (viewDialogOpen) {
      closeViewDialog();
    }
    setFormError(null);
    setIsCreating(false);
    setSelected(ch);
    setHighlightedId(ch.id);
    hydrateForm(ch);
    captureEditFormBaselineFromCheque(ch);
    setEditDialogOpen(true);
  }

  function openViewCheque(ch: Cheque) {
    if (createDialogOpen) {
      closeCreateDialog();
    }
    if (editDialogOpen) {
      closeEditDialog();
    }
    setFormError(null);
    setIsCreating(false);
    setSelected(ch);
    setHighlightedId(ch.id);
    hydrateForm(ch);
    setViewDialogOpen(true);
  }

  function restoreCreateFormBaseline() {
    const baseline = createFormBaselineRef.current;
    if (!baseline) {
      clearForm();
      setSeriesEnabled(false);
      return;
    }
    setCreditId(baseline.creditId);
    setDebitId(baseline.debitId);
    setSummary(baseline.summary);
    setChequeNumber(baseline.chequeNumber);
    setIssueDate(baseline.issueDate);
    setAmount(baseline.amount);
    setPartyId(baseline.partyId);
    setSeriesEnabled(baseline.seriesEnabled);
    setIncrementUnit(baseline.incrementUnit);
    setIncrementN(baseline.incrementN);
    setSeriesStopMode(baseline.seriesStopMode);
    setSeriesCount(baseline.seriesCount);
    setSeriesEndDate(baseline.seriesEndDate);
    setSeriesPreview(null);
    setFormError(null);
    setCreateDialogView("form");
  }

  function closeCreateDialog() {
    setCreateDialogOpen(false);
    setIsCreating(false);
    setSeriesEnabled(false);
    setSeriesPreview(null);
    setCreateDialogView("form");
  }

  function handleNewCheque() {
    if (editDialogOpen) {
      closeEditDialog();
    }
    if (viewDialogOpen) {
      closeViewDialog();
    }
    setFormError(null);
    setIsCreating(true);
    setSelected(null);
    setSeriesEnabled(false);
    setSeriesPreview(null);
    setCreateDialogView("form");
    clearForm();
    createFormBaselineRef.current = {
      creditId: pickEligibleDefault(defaultCreditId, eligibleCreditAccounts),
      debitId: pickEligibleDefault(defaultDebitId, eligibleDebitAccounts),
      summary: "",
      chequeNumber: "",
      issueDate: new Date().toISOString().slice(0, 10),
      amount: "",
      partyId: "",
      seriesEnabled: false,
      incrementUnit: "months",
      incrementN: "1",
      seriesStopMode: "count",
      seriesCount: "5",
      seriesEndDate: "",
    };
    setCreateDialogOpen(true);
  }

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

  function buildSeriesPayload(): ChequeSeriesCreateInput | null {
    const normalizedAmount = parseChequeAmount(amount);
    if (!creditId || !debitId || !summary.trim() || !chequeNumber || !issueDate || !normalizedAmount) {
      return null;
    }
    const startNum = Number(chequeNumber);
    const n = Number(incrementN);
    if (!Number.isInteger(startNum) || startNum <= 0 || !Number.isInteger(n) || n <= 0) {
      return null;
    }
    const schedule: ChequeSeriesCreateInput["schedule"] = {
      increment_unit: incrementUnit,
      increment_n: n,
    };
    if (seriesStopMode === "count") {
      const count = Number(seriesCount);
      if (!Number.isInteger(count) || count < 1) {
        return null;
      }
      schedule.count = count;
    } else {
      if (!seriesEndDate) {
        return null;
      }
      schedule.end_date = seriesEndDate;
    }
    return {
      credit_account_id: Number(creditId),
      debit_account_id: Number(debitId),
      summary: summary.trim(),
      starting_cheque_number: startNum,
      starting_issue_date: issueDate,
      amount: normalizedAmount,
      party_id: partyId ? Number(partyId) : null,
      schedule,
    };
  }

  async function runSeriesPreview(): Promise<boolean> {
    setFormError(null);
    const payload = buildSeriesPayload();
    if (!payload) {
      setFormError(
        "Credit account, debit account, summary, starting cheque number, issue date, amount, and schedule fields are required.",
      );
      setSeriesPreview(null);
      return false;
    }
    setSeriesPreviewLoading(true);
    try {
      const preview = await previewChequeSeries(payload);
      setSeriesPreview(preview);
      return true;
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Preview failed");
      setSeriesPreview(null);
      return false;
    } finally {
      setSeriesPreviewLoading(false);
    }
  }

  async function handleShowSeriesPreview() {
    const ok = await runSeriesPreview();
    if (ok) {
      setCreateDialogView("preview");
    }
  }

  const seriesHasConflict = seriesPreview?.rows.some((r) => r.number_conflict) ?? false;

  function handleSelectRow(ch: Cheque) {
    setFormError(null);
    if (createDialogOpen) {
      closeCreateDialog();
    }
    setIsCreating(false);
    setHighlightedId(ch.id);
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
    const normalizedAmount = parseChequeAmount(amount);
    if (!creditId || !debitId || !summary.trim() || !chequeNumber || !issueDate || !normalizedAmount) {
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
        if (seriesEnabled) {
          if (!seriesPreview || seriesHasConflict) {
            setFormError(
              seriesHasConflict
                ? "Resolve open-cheque number conflicts before creating the series."
                : "Preview the series before creating cheques.",
            );
            setFormBusy(false);
            return;
          }
          const payload = buildSeriesPayload();
          if (!payload) {
            setFormError("Complete all series fields before creating.");
            return;
          }
          const created = await createChequeSeries(payload);
          closeCreateDialog();
          if (created.length > 0) {
            setSelected(created[0]);
          }
        } else {
          const created = await createCheque({
            credit_account_id: Number(creditId),
            debit_account_id: Number(debitId),
            summary: summary.trim(),
            cheque_number: num,
            issue_date: issueDate,
            amount: normalizedAmount,
            party_id: partyId ? Number(partyId) : null,
          });
          closeCreateDialog();
          setSelected(created);
        }
        await reloadList();
        await refreshDefaults();
      } else if (editDialogOpen && selected) {
        const updated = await patchCheque(selected.id, {
          credit_account_id: Number(creditId),
          debit_account_id: Number(debitId),
          summary: summary.trim(),
          cheque_number: num,
          issue_date: issueDate,
          amount: normalizedAmount,
          party_id: partyId ? Number(partyId) : null,
        });
        setSelected(updated);
        closeEditDialog();
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
      closeEditDialog();
      openViewCheque(updated);
      await reloadList();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Void failed");
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
        if (editDialogOpen) {
          closeEditDialog();
          openViewCheque(updated);
        }
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
        if (viewDialogOpen) {
          closeViewDialog();
          openEditCheque(updated);
        } else if (editDialogOpen) {
          hydrateForm(updated);
          captureEditFormBaselineFromCheque(updated);
        }
      }
      await reloadList();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Re-open failed");
    }
  }

  const creditPickerOptions = buildPickerOptions(
    eligibleCreditAccounts,
    accounts,
    selected ? selected.credit_account_id : null,
  );
  const debitPickerOptions = buildPickerOptions(
    eligibleDebitAccounts,
    accounts,
    selected ? selected.debit_account_id : null,
  );
  const formReadOnly = viewDialogOpen;
  const editingId = editDialogOpen && selected ? selected.id : null;

  const chequeFieldsValid = useMemo(() => {
    const normalizedAmount = parseChequeAmount(amount);
    return Boolean(
      creditId && debitId && summary.trim() && chequeNumber && issueDate && normalizedAmount,
    );
  }, [amount, chequeNumber, creditId, debitId, issueDate, summary]);

  const canSubmitEdit = chequeFieldsValid && editDialogOpen && editingId != null;
  const canSubmitCreate = useMemo(() => {
    if (!createDialogOpen) {
      return false;
    }
    if (createDialogView === "preview") {
      return Boolean(seriesPreview && !seriesHasConflict);
    }
    if (seriesEnabled) {
      return buildSeriesPayload() != null;
    }
    return chequeFieldsValid;
  }, [
    chequeFieldsValid,
    createDialogOpen,
    createDialogView,
    seriesEnabled,
    seriesHasConflict,
    seriesPreview,
    amount,
    chequeNumber,
    creditId,
    debitId,
    incrementN,
    incrementUnit,
    issueDate,
    partyId,
    seriesCount,
    seriesEndDate,
    seriesStopMode,
    summary,
  ]);

  useChequeCreateModalShortcuts({
    createDialogOpen,
    createDialogView,
    editDialogOpen,
    viewDialogOpen,
    canSubmitCreate,
    canSubmitEdit,
    createSubmitting: formBusy || seriesPreviewLoading,
    editSubmitting: formBusy,
    newShortcutActive: !createDialogOpen && !editDialogOpen && !viewDialogOpen,
    onCreateSave: () => {
      if (createDialogView === "preview") {
        createFormRef.current?.requestSubmit();
      } else if (seriesEnabled) {
        void handleShowSeriesPreview();
      } else {
        createFormRef.current?.requestSubmit();
      }
    },
    onEditSave: () => {
      editFormRef.current?.requestSubmit();
    },
    onCreateClose: closeCreateDialog,
    onEditClose: closeEditDialog,
    onViewClose: closeViewDialog,
    onCreateReturnToForm: () => {
      setCreateDialogView("form");
      setFormError(null);
    },
    onCreateRevertForm: restoreCreateFormBaseline,
    onEditRevertForm: restoreEditFormBaseline,
    onNewCheque: handleNewCheque,
  });

  function clearSeriesPreview() {
    setSeriesPreview(null);
  }

  function renderChequeFields(options: {
    startingNumberLabel: string;
    issueDateLabel: string;
    onFieldChange?: () => void;
  }) {
    const { startingNumberLabel, issueDateLabel, onFieldChange } = options;
    const bumpSeries = () => {
      onFieldChange?.();
      setSeriesPreview(null);
      setCreateDialogView("form");
    };
    return (
      <div className="cheque-form-grid">
        <div className="cheque-form-col">
          <label>
            {issueDateLabel}
            <input
              type="date"
              value={issueDate}
              onChange={(e) => {
                setIssueDate(e.target.value);
                bumpSeries();
              }}
              required
              disabled={formReadOnly}
            />
          </label>
          <label>
            {startingNumberLabel}
            <input
              type="number"
              min={1}
              step={1}
              value={chequeNumber}
              onChange={(e) => {
                setChequeNumber(e.target.value);
                bumpSeries();
              }}
              required
              disabled={formReadOnly}
            />
          </label>
          <label>
            Amount
            <input
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
                bumpSeries();
              }}
              onBlur={() => {
                const normalized = parseChequeAmount(amount);
                if (normalized) {
                  setAmount(normalized);
                }
              }}
              required
              disabled={formReadOnly}
            />
          </label>
        </div>
        <div className="cheque-form-col">
          <label>
            Credit account (cheque)
            <select
              value={creditId}
              onChange={(e) => {
                setCreditId(e.target.value);
                bumpSeries();
              }}
              required
              disabled={formReadOnly}
            >
              <option value="">Select account</option>
              {creditPickerOptions.map(({ account, eligible }) => (
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
              onChange={(e) => {
                setDebitId(e.target.value);
                bumpSeries();
              }}
              required
              disabled={formReadOnly}
            >
              <option value="">Select account</option>
              {debitPickerOptions.map(({ account, eligible }) => (
                <option key={account.id} value={account.id}>
                  {eligible ? eligibleLabel(account) : ineligibleLabel(account)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Party (optional)
            <select
              value={partyId}
              onChange={(e) => {
                setPartyId(e.target.value);
                bumpSeries();
              }}
              disabled={formReadOnly}
            >
              <option value="">None</option>
              {partyOptions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="cheque-form-summary">
          Summary
          <input
            value={summary}
            onChange={(e) => {
              setSummary(e.target.value);
              bumpSeries();
            }}
            required
            disabled={formReadOnly}
          />
        </label>
      </div>
    );
  }

  function renderSeriesEnableCheckbox() {
    return (
      <label className="cheque-series-enable">
        <input
          type="checkbox"
          checked={seriesEnabled}
          onChange={(e) => {
            const checked = e.target.checked;
            setSeriesEnabled(checked);
            setSeriesPreview(null);
            setCreateDialogView("form");
            if (!checked) {
              setSeriesEndDate("");
            }
          }}
        />
        Create as series (post-dated)
      </label>
    );
  }

  function renderSeriesScheduleFields() {
    return (
      <div className={seriesEnabled ? "cheque-series-schedule" : "cheque-series-schedule cheque-series-disabled"}>
        <div className="cheque-series-row">
          <label>
            Increment
            <select
              value={incrementUnit}
              onChange={(e) => {
                setIncrementUnit(e.target.value as ChequeIncrementUnit);
                setSeriesPreview(null);
                setCreateDialogView("form");
              }}
              disabled={!seriesEnabled}
              tabIndex={seriesEnabled ? 0 : -1}
            >
              <option value="days">days</option>
              <option value="weeks">weeks</option>
              <option value="months">months</option>
            </select>
          </label>
          <label>
            Every (n)
            <input
              type="number"
              min={1}
              step={1}
              value={incrementN}
              onChange={(e) => {
                setIncrementN(e.target.value);
                setSeriesPreview(null);
                setCreateDialogView("form");
              }}
              disabled={!seriesEnabled}
              tabIndex={seriesEnabled ? 0 : -1}
            />
          </label>
          <fieldset className="cheque-series-stop" disabled={!seriesEnabled}>
            <legend className="cheque-series-stop-label">Stop after</legend>
            <label className="cheque-series-inline-radio">
              <input
                type="radio"
                name="series-stop"
                checked={seriesStopMode === "count"}
                onChange={() => {
                  setSeriesStopMode("count");
                  setSeriesPreview(null);
                  setCreateDialogView("form");
                }}
                tabIndex={seriesEnabled ? 0 : -1}
              />
              Count
            </label>
            <label className="cheque-series-inline-radio">
              <input
                type="radio"
                name="series-stop"
                checked={seriesStopMode === "end"}
                onChange={() => {
                  setSeriesStopMode("end");
                  setSeriesPreview(null);
                  setCreateDialogView("form");
                }}
                tabIndex={seriesEnabled ? 0 : -1}
              />
              End date
            </label>
          </fieldset>
          {seriesStopMode === "count" ? (
            <label>
              Number of cheques
              <input
                type="number"
                min={1}
                max={maxChequeSeriesCount}
                step={1}
                value={seriesCount}
                onChange={(e) => {
                  setSeriesCount(e.target.value);
                  setSeriesPreview(null);
                  setCreateDialogView("form");
                }}
                disabled={!seriesEnabled}
                tabIndex={seriesEnabled ? 0 : -1}
              />
            </label>
          ) : (
            <label>
              End date (inclusive)
              <input
                type="date"
                value={seriesEndDate}
                onChange={(e) => {
                  setSeriesEndDate(e.target.value);
                  setSeriesPreview(null);
                  setCreateDialogView("form");
                }}
                disabled={!seriesEnabled}
                tabIndex={seriesEnabled ? 0 : -1}
              />
            </label>
          )}
        </div>
        <p className="muted cheque-series-hint">
          Monthly increments use the day-of-month from the first issue date. Maximum {maxChequeSeriesCount} cheques per
          series.
        </p>
      </div>
    );
  }

  function renderSeriesPreviewPanel() {
    if (!seriesPreview) {
      return null;
    }
    const previewColSpan = 4;
    return (
      <div className="cheque-series-preview-panel">
        <table className="cheque-series-preview-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Issue date</th>
              <th>Summary</th>
              <th className="cheque-amount-col">Amount</th>
            </tr>
          </thead>
          <tbody>
            {seriesPreview.rows.map((row: ChequeSeriesPreviewRow) => (
              <Fragment key={row.cheque_number}>
                <tr>
                  <td>{row.cheque_number}</td>
                  <td>{row.issue_date}</td>
                  <td>{summary.trim()}</td>
                  <td className="cheque-amount-col">{formatChequeCurrency(row.amount)}</td>
                </tr>
                {row.number_conflict && (
                  <tr className="cheque-preview-error-row">
                    <td colSpan={previewColSpan}>
                      <div className="journal-review-message-card" role="alert">
                        <p className="journal-review-message-text">
                          Open cheque number already in use on this credit account
                        </p>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        <p className="muted">{seriesPreview.series_count} cheques in series</p>
      </div>
    );
  }


  return (
    <>
      <section className="card journal-card-wide">
        <div className="cheque-register-toolbar">
          <h2>Cheque register</h2>
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
              aria-label={newEntityAriaLabel("New cheque", isMac)}
              title={newActionTooltip(isMac)}
              aria-keyshortcuts={newAriaKeyShortcuts(isMac)}
              onClick={handleNewCheque}
            >
              <FilePlus2 size={18} strokeWidth={2} aria-hidden />
            </TableRowIconButton>
          </div>
        </div>
        <p className="muted">
          New cheques are always <strong>open</strong>. <strong>Cleared</strong> is set only when a clearing entry is
          posted against this cheque. Use <strong>Void</strong> or <strong>Re-open</strong> for void workflow only.
        </p>

        <div className="cheque-register-filters journal-filters-line">
          <label className="journal-filter-slot journal-filter-slot-select">
            <span className="journal-filter-inline-label">Status</span>
            <select
              className="journal-filter-control"
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
          <ChequePartyFilterMultiDropdown
            label="Party"
            ariaFilterLabel="Filter cheques by party"
            options={filterOptions.parties}
            selectedIds={selectedPartyIds}
            onIdsChange={setSelectedPartyIds}
          />
          <JournalFilterMultiDropdown
            label="Credit account"
            ariaFilterLabel="Filter cheques by credit account"
            options={filterOptions.credit_accounts.flatMap((a) =>
              a.id == null ? [] : [{ id: a.id, name: a.name }],
            )}
            selectedIds={selectedCreditAccountIds}
            onIdsChange={setSelectedCreditAccountIds}
          />
          <JournalFilterMultiDropdown
            label="Debit account"
            ariaFilterLabel="Filter cheques by debit account"
            options={filterOptions.debit_accounts.flatMap((a) =>
              a.id == null ? [] : [{ id: a.id, name: a.name }],
            )}
            selectedIds={selectedDebitAccountIds}
            onIdsChange={setSelectedDebitAccountIds}
          />
          <label className="journal-filter-slot journal-filter-slot-date">
            <span className="journal-filter-inline-label">Issue from</span>
            <input
              className="journal-filter-control"
              type="date"
              value={issueFromDate}
              onChange={(e) => setIssueFromDate(e.target.value)}
              aria-label="Filter cheques issue from date"
            />
          </label>
          <label className="journal-filter-slot journal-filter-slot-date">
            <span className="journal-filter-inline-label">Issue to</span>
            <input
              className="journal-filter-control"
              type="date"
              value={issueToDate}
              onChange={(e) => setIssueToDate(e.target.value)}
              aria-label="Filter cheques issue to date"
            />
          </label>
          <label className="journal-filter-slot journal-filter-slot-date">
            <span className="journal-filter-inline-label">Cleared from</span>
            <input
              className="journal-filter-control"
              type="date"
              value={clearedFromDate}
              onChange={(e) => setClearedFromDate(e.target.value)}
              aria-label="Filter cheques cleared from date"
            />
          </label>
          <label className="journal-filter-slot journal-filter-slot-date">
            <span className="journal-filter-inline-label">Cleared to</span>
            <input
              className="journal-filter-control"
              type="date"
              value={clearedToDate}
              onChange={(e) => setClearedToDate(e.target.value)}
              aria-label="Filter cheques cleared to date"
            />
          </label>
          <label className="journal-filter-slot journal-filter-slot-number">
            <span className="journal-filter-inline-label">Min amount</span>
            <input
              className="journal-filter-control"
              type="number"
              min={0}
              step={0.01}
              inputMode="decimal"
              value={minAmount}
              onChange={(e) => setMinAmount(e.target.value)}
              aria-label="Filter cheques minimum amount"
            />
          </label>
          <label className="journal-filter-slot journal-filter-slot-number">
            <span className="journal-filter-inline-label">Max amount</span>
            <input
              className="journal-filter-control"
              type="number"
              min={0}
              step={0.01}
              inputMode="decimal"
              value={maxAmount}
              onChange={(e) => setMaxAmount(e.target.value)}
              aria-label="Filter cheques maximum amount"
            />
          </label>
          <label className="journal-filter-slot journal-filter-slot-select">
            <span className="journal-filter-inline-label">Summary</span>
            <input
              className="journal-filter-control"
              type="search"
              value={summaryFilter}
              onChange={(e) => setSummaryFilter(e.target.value)}
              aria-label="Filter cheques by summary"
              placeholder="Regex on summary"
            />
          </label>
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
                <th>Cleared</th>
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
                  <td colSpan={10} className="muted">
                    Loading…
                  </td>
                </tr>
              ) : cheques.length === 0 ? (
                <tr>
                  <td colSpan={10} className="muted">
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
                      background: highlightedId === ch.id ? "var(--bg-subtle)" : undefined,
                    }}
                  >
                    <td>{statusLabel(ch.status)}</td>
                    <td>{ch.cheque_number}</td>
                    <td>{ch.summary}</td>
                    <td>{ch.issue_date}</td>
                    <td>{ch.cleared_date ?? "—"}</td>
                    <td className="cheque-amount-col">{formatChequeCurrency(ch.amount)}</td>
                    <td>{accountName(ch.credit_account_id)}</td>
                    <td>{accountName(ch.debit_account_id)}</td>
                    <td>{partyName(ch.party_id)}</td>
                    <td>
                      <div className="table-row-actions">
                        {ch.status === "cleared" || ch.status === "void" ? (
                          <>
                            <TableRowIconButton
                              type="button"
                              aria-label={`View cheque #${ch.cheque_number}`}
                              title="View cheque"
                              onClick={(e) => {
                                e.stopPropagation();
                                openViewCheque(ch);
                              }}
                            >
                              <Eye size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                            {ch.status === "void" && (
                              <TableRowIconButton
                                type="button"
                                aria-label={`Re-open cheque #${ch.cheque_number}`}
                                title="Re-open cheque"
                                onClick={(e) => void reopenRow(ch, e)}
                              >
                                <SquareCheck size={18} strokeWidth={2} aria-hidden />
                              </TableRowIconButton>
                            )}
                          </>
                        ) : (
                          <>
                            <TableRowIconButton
                              type="button"
                              aria-label={`Edit cheque #${ch.cheque_number}`}
                              title="Edit cheque"
                              onClick={(e) => {
                                e.stopPropagation();
                                openEditCheque(ch);
                              }}
                            >
                              <Pencil size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                            <TableRowIconButton
                              type="button"
                              aria-label={`Void cheque #${ch.cheque_number}`}
                              title="Void cheque"
                              onClick={(e) => void voidRow(ch, e)}
                            >
                              <Ban size={18} strokeWidth={2} aria-hidden />
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

      {editDialogOpen && selected && (
        <dialog
          ref={editDialogRef}
          className="cheque-dialog"
          aria-labelledby="cheque-edit-dialog-title"
          onClose={closeEditDialog}
        >
          <form
            ref={editFormRef}
            method="dialog"
            className="cheque-dialog-inner"
            noValidate
            onSubmit={(e) => void handleSave(e)}
          >
            <div className="cheque-dialog-header">
              <h2 id="cheque-edit-dialog-title">{`Edit cheque #${selected.cheque_number}`}</h2>
              <button type="button" className="button-secondary" onClick={closeEditDialog}>
                Close
              </button>
            </div>

            <p>
              <strong>Status:</strong> {statusLabel(selected.status)}
            </p>

            {renderChequeFields({
              issueDateLabel: "Issue date",
              startingNumberLabel: "Cheque number",
            })}

            {formError && <p className="error-text">{formError}</p>}

            <div className="dialog-actions">
              <button
                type="button"
                className="button-secondary"
                onClick={closeEditDialog}
                title={discardActionTooltip(isMac)}
                aria-label={discardActionTooltip(isMac)}
                aria-keyshortcuts={discardAriaKeyShortcuts(isMac)}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={formBusy}
                title={saveActionTooltip(isMac)}
                aria-label={isMac ? "Save changes (⌘+S)" : "Save changes (Ctrl+S)"}
                aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
              >
                Save changes
              </button>
              {canVoidOrReopen && savedCheque.status === "open" && (
                <button type="button" onClick={() => void handleVoid()} disabled={formBusy}>
                  Void cheque
                </button>
              )}
            </div>
          </form>
        </dialog>
      )}

      {viewDialogOpen && selected && (
        <dialog
          ref={viewDialogRef}
          className="cheque-dialog"
          aria-labelledby="cheque-view-dialog-title"
          onClose={closeViewDialog}
        >
          <div className="cheque-dialog-inner">
            <div className="cheque-dialog-header">
              <h2 id="cheque-view-dialog-title">{`View cheque #${selected.cheque_number}`}</h2>
              <button type="button" className="button-secondary" onClick={closeViewDialog}>
                Close
              </button>
            </div>

            <p>
              <strong>Status:</strong> {statusLabel(selected.status)}
              {selected.cleared_date && (
                <span className="muted"> (cleared {selected.cleared_date})</span>
              )}
            </p>

            {renderChequeFields({
              issueDateLabel: "Issue date",
              startingNumberLabel: "Cheque number",
            })}

            <div className="dialog-actions">
              <button type="button" className="button-secondary" onClick={closeViewDialog} aria-label="Close">
                Cancel
              </button>
            </div>
          </div>
        </dialog>
      )}

      {createDialogOpen && (
      <dialog
        ref={createDialogRef}
        className={createDialogView === "preview" ? "cheque-dialog cheque-dialog-preview" : "cheque-dialog"}
        aria-labelledby="cheque-create-dialog-title"
        onClose={closeCreateDialog}
      >
        <form
          ref={createFormRef}
          method="dialog"
          className="cheque-dialog-inner"
          noValidate
          onSubmit={(e) => void handleSave(e)}
        >
          <div className="cheque-dialog-header">
            <h2 id="cheque-create-dialog-title">
              {createDialogView === "preview" ? "Preview cheque series" : "New cheque"}
            </h2>
            <button type="button" className="button-secondary" onClick={closeCreateDialog}>
              Close
            </button>
          </div>

          {createDialogView === "form" ? (
            <>
              {renderChequeFields({
                issueDateLabel: seriesEnabled ? "First issue date" : "Issue date",
                startingNumberLabel: seriesEnabled ? "Starting cheque number" : "Cheque number",
                onFieldChange: clearSeriesPreview,
              })}

              {renderSeriesEnableCheckbox()}
              {renderSeriesScheduleFields()}

              {formError && <p className="error-text">{formError}</p>}

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
                {seriesEnabled ? (
                  <button
                    type="button"
                    disabled={formBusy || seriesPreviewLoading}
                    onClick={() => void handleShowSeriesPreview()}
                  >
                    {seriesPreviewLoading ? "Previewing…" : "Preview"}
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={formBusy}
                    title={saveActionTooltip(isMac)}
                    aria-label={isMac ? "Create cheque (⌘+S)" : "Create cheque (Ctrl+S)"}
                    aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
                  >
                    Create cheque
                  </button>
                )}
              </div>
            </>
          ) : (
            <>
              {renderSeriesPreviewPanel()}

              {formError && <p className="error-text">{formError}</p>}

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
                  className="button-secondary"
                  onClick={() => {
                    setCreateDialogView("form");
                    setFormError(null);
                  }}
                  title={previewReturnToFormActionTooltip(isMac)}
                  aria-label={previewReturnToFormActionTooltip(isMac)}
                  aria-keyshortcuts={previewReturnToFormAriaKeyShortcuts(isMac)}
                >
                  Back to form
                </button>
                <button
                  type="submit"
                  disabled={formBusy || seriesHasConflict || !seriesPreview}
                  title={saveActionTooltip(isMac)}
                  aria-label={isMac ? "Create series (⌘+S)" : "Create series (Ctrl+S)"}
                  aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
                >
                  Create series
                </button>
              </div>
            </>
          )}
        </form>
      </dialog>
      )}
    </>
  );
}
