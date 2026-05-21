import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NotebookPen, Paperclip, Pencil, Save } from "lucide-react";

import type { Account } from "../api/accounts";
import type { Cheque } from "../api/cheques";
import { getCheque, listCheques } from "../api/cheques";
import type { Party } from "../api/parties";
import { listAccrualPlans, type AccrualPlan } from "../api/accrualPlans";
import {
  createJournalEntry,
  getJournalEntry,
  listJournalEntries,
  updateJournalEntry,
  type ChequeAssociation,
  type JournalEntryListItem,
  type JournalEntryReviewMessage,
  type JournalEntryWrite,
} from "../api/journalEntries";
import { listImportBatches, type ImportBatchListItem } from "../api/importBatches";
import {
  createJournalEntryFilterPreset,
  listJournalEntryFilterPresets,
  updateJournalEntryFilterPreset,
  type JournalEntryFilterPreset,
  type JournalEntryFilterPresetDefinition,
} from "../api/journalEntryFilterPresets";
import { JournalEntryAttachmentsDialog } from "./JournalEntryAttachmentsDialog";
import { JournalEntryForm, type LineDraft } from "./JournalEntryForm";
import { JournalFilterMultiDropdown } from "./JournalFilterMultiDropdown";
import { TableRowIconButton } from "./TableRowIconButton";

const PAGE_SIZE = 50;

function sortedIds(ids: number[]): number[] {
  return [...ids].sort((a, b) => a - b);
}

function sameIdList(a: number[] | undefined, b: number[] | undefined): boolean {
  const aa = sortedIds(a ?? []);
  const bb = sortedIds(b ?? []);
  if (aa.length !== bb.length) return false;
  for (let i = 0; i < aa.length; i += 1) {
    if (aa[i] !== bb[i]) return false;
  }
  return true;
}

interface FilterState {
  fromDate: string;
  toDate: string;
  needsReviewOnly: boolean;
  accountIds: number[];
  partyIds: number[];
  accrualPlanIds: number[];
  amountLow: string;
  amountHigh: string;
  chequeAssociation: ChequeAssociation;
  /** CSV import file basename (matches API `import_basename`; #136). */
  importBasename: string;
}

const EMPTY_FILTER: FilterState = {
  fromDate: "",
  toDate: "",
  needsReviewOnly: false,
  accountIds: [],
  partyIds: [],
  accrualPlanIds: [],
  amountLow: "",
  amountHigh: "",
  chequeAssociation: "any",
  importBasename: "",
};

function definitionFromFilter(state: FilterState): JournalEntryFilterPresetDefinition {
  const def: JournalEntryFilterPresetDefinition = {};
  if (state.fromDate) def.from_date = state.fromDate;
  if (state.toDate) def.to_date = state.toDate;
  if (state.needsReviewOnly) def.needs_review = true;
  if (state.accountIds.length > 0) def.account_ids = sortedIds(state.accountIds);
  if (state.partyIds.length > 0) def.party_ids = sortedIds(state.partyIds);
  if (state.accrualPlanIds.length > 0) def.accrual_plan_ids = sortedIds(state.accrualPlanIds);
  if (state.amountLow !== "") def.amount_low = Number(state.amountLow);
  if (state.amountHigh !== "") def.amount_high = Number(state.amountHigh);
  if (state.chequeAssociation !== "any") def.cheque_association = state.chequeAssociation;
  const ib = state.importBasename.trim();
  if (ib !== "") def.import_basename = ib;
  return def;
}

function filterFromDefinition(def: JournalEntryFilterPresetDefinition): FilterState {
  return {
    fromDate: def.from_date ?? "",
    toDate: def.to_date ?? "",
    needsReviewOnly: def.needs_review === true,
    accountIds: sortedIds(def.account_ids ?? []),
    partyIds: sortedIds(def.party_ids ?? []),
    accrualPlanIds: sortedIds(def.accrual_plan_ids ?? []),
    amountLow: def.amount_low != null ? String(def.amount_low) : "",
    amountHigh: def.amount_high != null ? String(def.amount_high) : "",
    chequeAssociation: def.cheque_association ?? "any",
    importBasename: def.import_basename?.trim() ?? "",
  };
}

function filterMatchesDefinition(
  state: FilterState,
  def: JournalEntryFilterPresetDefinition,
): boolean {
  const normalized = filterFromDefinition(def);
  return (
    state.fromDate === normalized.fromDate &&
    state.toDate === normalized.toDate &&
    state.needsReviewOnly === normalized.needsReviewOnly &&
    state.amountLow === normalized.amountLow &&
    state.amountHigh === normalized.amountHigh &&
    state.chequeAssociation === normalized.chequeAssociation &&
    (state.importBasename || "") === (normalized.importBasename || "") &&
    sameIdList(state.accountIds, normalized.accountIds) &&
    sameIdList(state.partyIds, normalized.partyIds) &&
    sameIdList(state.accrualPlanIds, normalized.accrualPlanIds)
  );
}

function linesFromEntry(
  lines: {
    id: number;
    account_id: number;
    amount: string;
    account_name: string;
    party_id?: number | null;
    party_name?: string | null;
  }[],
): LineDraft[] {
  return lines.map((l) => ({
    key: `jl-${l.id}`,
    account_id: l.account_id,
    party_id: l.party_id ?? "",
    amount: l.amount,
    account_name: l.account_name,
    party_name: l.party_name ?? undefined,
  }));
}

interface JournalEntriesPanelProps {
  accounts: Account[];
  parties: Party[];
  accountsLoading: boolean;
  accountsError: string | null;
  /** After CSV import: open list filtered to this basename only (#136). */
  initialImportBasename?: string;
  onInitialImportBasenameApplied?: () => void;
}

export function JournalEntriesPanel({
  accounts,
  parties,
  accountsLoading,
  accountsError,
  initialImportBasename,
  onInitialImportBasenameApplied,
}: JournalEntriesPanelProps) {
  const [view, setView] = useState<"list" | "form">("list");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [entries, setEntries] = useState<JournalEntryListItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterState>(() =>
    initialImportBasename
      ? { ...EMPTY_FILTER, importBasename: initialImportBasename }
      : EMPTY_FILTER,
  );
  const [hasMore, setHasMore] = useState(false);

  const [accrualPlans, setAccrualPlans] = useState<AccrualPlan[]>([]);
  const [importBatches, setImportBatches] = useState<ImportBatchListItem[]>([]);
  const [presets, setPresets] = useState<JournalEntryFilterPreset[]>([]);
  const [appliedPresetId, setAppliedPresetId] = useState<number | null>(null);
  const [presetsError, setPresetsError] = useState<string | null>(null);

  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savePending, setSavePending] = useState(false);
  const saveDialogRef = useRef<HTMLDialogElement>(null);

  const [formEntryDate, setFormEntryDate] = useState("");
  const [formSummary, setFormSummary] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formReviewMessages, setFormReviewMessages] = useState<JournalEntryReviewMessage[]>([]);
  const [formLines, setFormLines] = useState<LineDraft[] | null>(null);
  const [formLoading, setFormLoading] = useState(false);
  const [formLoadError, setFormLoadError] = useState<string | null>(null);
  const [formChequeChoices, setFormChequeChoices] = useState<Cheque[]>([]);
  const [formInitialChequeId, setFormInitialChequeId] = useState<number | null>(null);
  const [attachmentsEntryId, setAttachmentsEntryId] = useState<number | null>(null);

  const listParams = useMemo(
    () => ({
      from_date: filter.fromDate || undefined,
      to_date: filter.toDate || undefined,
      needs_review: filter.needsReviewOnly || undefined,
      account_ids: filter.accountIds.length > 0 ? filter.accountIds : undefined,
      party_ids: filter.partyIds.length > 0 ? filter.partyIds : undefined,
      accrual_plan_ids:
        filter.accrualPlanIds.length > 0 ? filter.accrualPlanIds : undefined,
      amount_low: filter.amountLow !== "" ? Number(filter.amountLow) : undefined,
      amount_high: filter.amountHigh !== "" ? Number(filter.amountHigh) : undefined,
      cheque_association:
        filter.chequeAssociation !== "any" ? filter.chequeAssociation : undefined,
      import_basename: filter.importBasename.trim() || undefined,
    }),
    [filter],
  );

  const updateFilter = useCallback(
    (patch: Partial<FilterState>) => {
      setFilter((prev) => ({ ...prev, ...patch }));
      setAppliedPresetId(null);
    },
    [],
  );

  const refreshList = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const batch = await listJournalEntries({
        ...listParams,
        limit: PAGE_SIZE,
        offset: 0,
      });
      setEntries(batch);
      setHasMore(batch.length === PAGE_SIZE);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load journal entries");
    } finally {
      setListLoading(false);
    }
  }, [listParams]);

  useEffect(() => {
    if (view !== "list") {
      return;
    }
    void refreshList();
  }, [view, refreshList]);

  useEffect(() => {
    if (!initialImportBasename) {
      return;
    }
    onInitialImportBasenameApplied?.();
  }, [initialImportBasename, onInitialImportBasenameApplied]);

  useEffect(() => {
    void (async () => {
      try {
        const [planList, loadedPresets] = await Promise.all([
          listAccrualPlans(),
          listJournalEntryFilterPresets(),
        ]);
        setAccrualPlans(planList.plans);
        setPresets(loadedPresets);
      } catch (err) {
        setPresetsError(
          err instanceof Error ? err.message : "Failed to load filter presets",
        );
      }
    })();
  }, []);

  useEffect(() => {
    void listImportBatches().then(setImportBatches).catch(() => {
      setImportBatches([]);
    });
  }, []);

  async function loadMore() {
    setListLoading(true);
    setListError(null);
    try {
      const batch = await listJournalEntries({
        ...listParams,
        limit: PAGE_SIZE,
        offset: entries.length,
      });
      setEntries((prev) => [...prev, ...batch]);
      setHasMore(batch.length === PAGE_SIZE);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load journal entries");
    } finally {
      setListLoading(false);
    }
  }

  const appliedPreset = useMemo(
    () => presets.find((p) => p.id === appliedPresetId) ?? null,
    [presets, appliedPresetId],
  );

  const displayedPresetId = useMemo(() => {
    if (appliedPreset && filterMatchesDefinition(filter, appliedPreset.definition)) {
      return appliedPreset.id;
    }
    return null;
  }, [appliedPreset, filter]);

  const importBasenameOptions = useMemo(() => {
    const seen = new Set<string>();
    const out: ImportBatchListItem[] = [];
    for (const b of importBatches) {
      const k = b.basename.toLowerCase();
      if (seen.has(k)) {
        continue;
      }
      seen.add(k);
      out.push(b);
    }
    return out;
  }, [importBatches]);

  function applyPreset(presetId: number) {
    const preset = presets.find((p) => p.id === presetId);
    if (!preset) {
      return;
    }
    setFilter(filterFromDefinition(preset.definition));
    setAppliedPresetId(preset.id);
  }

  function openSaveDialog() {
    setSaveError(null);
    setSaveName(appliedPreset?.name ?? "");
    setSaveDialogOpen(true);
  }

  useEffect(() => {
    const el = saveDialogRef.current;
    if (!el) return;
    if (saveDialogOpen && !el.open) {
      el.showModal();
    } else if (!saveDialogOpen && el.open) {
      el.close();
    }
  }, [saveDialogOpen]);

  async function handleSavePreset(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = saveName.trim();
    if (!name) {
      setSaveError("Name must not be empty.");
      return;
    }
    setSavePending(true);
    setSaveError(null);
    try {
      const definition = definitionFromFilter(filter);
      const existing = presets.find(
        (p) => p.name.toLowerCase() === name.toLowerCase(),
      );
      if (existing) {
        const confirmed = window.confirm(
          `A preset named "${existing.name}" already exists. Overwrite it?`,
        );
        if (!confirmed) {
          setSavePending(false);
          return;
        }
        const updated = await updateJournalEntryFilterPreset(existing.id, {
          name,
          definition,
        });
        setPresets((prev) =>
          prev.map((p) => (p.id === updated.id ? updated : p)).sort((a, b) =>
            a.name.localeCompare(b.name),
          ),
        );
        setAppliedPresetId(updated.id);
      } else {
        const created = await createJournalEntryFilterPreset({ name, definition });
        setPresets((prev) =>
          [...prev, created].sort((a, b) => a.name.localeCompare(b.name)),
        );
        setAppliedPresetId(created.id);
      }
      setSaveDialogOpen(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save preset");
    } finally {
      setSavePending(false);
    }
  }

  async function openCreate() {
    setEditingId(null);
    setFormInitialChequeId(null);
    setFormEntryDate(new Date().toISOString().slice(0, 10));
    setFormSummary("");
    setFormDescription("");
    setFormReviewMessages([]);
    setFormLines(null);
    setFormLoadError(null);
    setView("form");
    setFormLoading(true);
    try {
      const open = await listCheques({ status: "open" });
      setFormChequeChoices(open);
    } catch {
      setFormChequeChoices([]);
    } finally {
      setFormLoading(false);
    }
  }

  async function openEdit(id: number) {
    setEditingId(id);
    setFormLoadError(null);
    setFormLoading(true);
    setView("form");
    try {
      const [entry, open] = await Promise.all([
        getJournalEntry(id),
        listCheques({ status: "open" }),
      ]);
      let choices = [...open];
      const cid = entry.cheque_id ?? null;
      if (cid != null) {
        const linked = await getCheque(cid);
        if (!choices.some((c) => c.id === linked.id)) {
          choices = [...choices, linked];
        }
      }
      setFormChequeChoices(choices);
      setFormInitialChequeId(cid);
      setFormEntryDate(entry.entry_date);
      setFormSummary(entry.summary);
      setFormDescription(entry.description ?? "");
      setFormReviewMessages(entry.review_messages ?? []);
      setFormLines(linesFromEntry(entry.lines));
    } catch (err) {
      setFormLoadError(err instanceof Error ? err.message : "Failed to load entry");
      setFormLines(null);
      setFormChequeChoices([]);
      setFormInitialChequeId(null);
    } finally {
      setFormLoading(false);
    }
  }

  async function handleSubmit(payload: JournalEntryWrite) {
    if (editingId == null) {
      await createJournalEntry(payload);
    } else {
      await updateJournalEntry(editingId, payload);
    }
    setView("list");
    await refreshList();
  }

  async function reloadReviewMessagesForEditor() {
    if (editingId == null) {
      return;
    }
    const entry = await getJournalEntry(editingId);
    setFormReviewMessages(entry.review_messages ?? []);
  }

  function handleCancelForm() {
    setView("list");
    setEditingId(null);
    setFormSummary("");
    setFormLines(null);
    setFormLoadError(null);
    setFormChequeChoices([]);
    setFormInitialChequeId(null);
  }

  if (accountsLoading && accounts.length === 0) {
    return (
      <section className="card journal-card-wide">
        <p>Loading chart of accounts…</p>
      </section>
    );
  }

  if (accountsError && accounts.length === 0) {
    return (
      <section className="card journal-card-wide">
        <p className="error" role="alert">
          {accountsError}
        </p>
        <p className="muted">Fix account loading to use journal lines.</p>
      </section>
    );
  }

  const attachmentsDialog = (
    <JournalEntryAttachmentsDialog
      entryId={attachmentsEntryId}
      onDismiss={() => setAttachmentsEntryId(null)}
    />
  );

  if (view === "form") {
    if (formLoading) {
      return (
        <>
          {attachmentsDialog}
          <p>{editingId == null ? "Loading…" : "Loading entry…"}</p>
        </>
      );
    }
    if (formLoadError) {
      return (
        <>
          {attachmentsDialog}
          <div className="card">
            <p className="error" role="alert">
              {formLoadError}
            </p>
            <button type="button" className="button-secondary" onClick={handleCancelForm}>
              Back to list
            </button>
          </div>
        </>
      );
    }
    return (
      <>
        {attachmentsDialog}
        <section className="card journal-card-wide">
          <JournalEntryForm
            key={editingId ?? "new"}
            mode={editingId == null ? "create" : "edit"}
            accounts={accounts}
            parties={parties}
            initialEntryDate={formEntryDate}
            initialSummary={formSummary}
            initialDescription={formDescription}
            reviewMessages={formReviewMessages}
            entryId={editingId}
            onReviewMessagesChanged={() => void reloadReviewMessagesForEditor()}
            initialLines={formLines}
            onSubmit={handleSubmit}
            onCancel={handleCancelForm}
            onOpenAttachments={
              editingId != null ? () => setAttachmentsEntryId(editingId) : undefined
            }
            chequeLinkChoices={formChequeChoices}
            initialChequeId={formInitialChequeId}
          />
        </section>
      </>
    );
  }

  return (
    <>
      {attachmentsDialog}
      <section className="card journal-card-wide">
      {accounts.length === 0 && (
        <p className="muted banner-info">
          Add at least two accounts under <strong>Accounts</strong> before posting journal lines.
        </p>
      )}
      <div className="journal-list-toolbar journal-list-toolbar-with-filters">
        <h2>Journal entries</h2>
        <div className="journal-filters-line">
          <TableRowIconButton
            type="button"
            aria-label="Save current filter as preset"
            title="Save current filter as preset"
            onClick={openSaveDialog}
          >
            <Save size={18} strokeWidth={2} aria-hidden />
          </TableRowIconButton>
          <label className="journal-filter-slot journal-filter-slot-select">
          <span className="journal-filter-inline-label">Filter Preset</span>
          <select
            className="journal-filter-control"
            aria-label="Filter preset"
            value={displayedPresetId != null ? String(displayedPresetId) : ""}
            onChange={(e) => {
              const v = e.target.value;
              if (v === "") {
                setAppliedPresetId(null);
                return;
              }
              applyPreset(Number(v));
            }}
          >
            <option value="">— None —</option>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <JournalFilterMultiDropdown
          label="Accounts"
          ariaFilterLabel="Filter by accounts"
          options={accounts.map((a) => ({ id: a.id, name: a.name }))}
          selectedIds={filter.accountIds}
          onIdsChange={(ids) => updateFilter({ accountIds: ids })}
        />
        <JournalFilterMultiDropdown
          label="Parties"
          ariaFilterLabel="Filter by parties"
          options={parties.map((p) => ({ id: p.id, name: p.name }))}
          selectedIds={filter.partyIds}
          onIdsChange={(ids) => updateFilter({ partyIds: ids })}
        />
        <JournalFilterMultiDropdown
          label="Accrual Plans"
          ariaFilterLabel="Filter by accrual plans"
          options={accrualPlans.map((p) => ({ id: p.id, name: p.name }))}
          selectedIds={filter.accrualPlanIds}
          onIdsChange={(ids) => updateFilter({ accrualPlanIds: ids })}
        />
        <label className="journal-filter-slot journal-filter-slot-select">
          <span className="journal-filter-inline-label">Import file</span>
          <select
            className="journal-filter-control"
            aria-label="Filter by CSV import file basename"
            value={filter.importBasename}
            onChange={(e) => updateFilter({ importBasename: e.target.value })}
          >
            <option value="">Any</option>
            {filter.importBasename.trim() !== "" &&
              !importBasenameOptions.some(
                (b) =>
                  b.basename.toLowerCase() === filter.importBasename.trim().toLowerCase(),
              ) && (
                <option value={filter.importBasename}>{filter.importBasename}</option>
              )}
            {importBasenameOptions.map((b) => (
              <option key={b.id} value={b.basename}>
                {b.basename}
              </option>
            ))}
          </select>
        </label>
        <label className="journal-filter-slot journal-filter-slot-select">
          <span className="journal-filter-inline-label">Cheque</span>
          <select
            className="journal-filter-control"
            aria-label="Filter by cheque association"
            value={filter.chequeAssociation}
            onChange={(e) =>
              updateFilter({ chequeAssociation: e.target.value as ChequeAssociation })
            }
          >
            <option value="any">Any</option>
            <option value="with_cheque">Has cheque</option>
            <option value="without_cheque">No cheque</option>
          </select>
        </label>
        <label className="journal-filter-slot journal-filter-inline-checkbox">
          <input
            type="checkbox"
            checked={filter.needsReviewOnly}
            onChange={(e) => updateFilter({ needsReviewOnly: e.target.checked })}
          />
          <span>Requires review</span>
        </label>
        <label className="journal-filter-slot journal-filter-slot-number">
          <span className="journal-filter-inline-label">Amount Low</span>
          <input
            className="journal-filter-control"
            aria-label="Filter amount low"
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            value={filter.amountLow}
            onChange={(e) => updateFilter({ amountLow: e.target.value })}
          />
        </label>
        <label className="journal-filter-slot journal-filter-slot-number">
          <span className="journal-filter-inline-label">Amount High</span>
          <input
            className="journal-filter-control"
            aria-label="Filter amount high"
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            value={filter.amountHigh}
            onChange={(e) => updateFilter({ amountHigh: e.target.value })}
          />
        </label>
        <label className="journal-filter-slot journal-filter-slot-date">
          <span className="journal-filter-inline-label">From Date</span>
          <input
            className="journal-filter-control"
            aria-label="Filter from date"
            type="date"
            value={filter.fromDate}
            onChange={(e) => updateFilter({ fromDate: e.target.value })}
          />
        </label>
        <label className="journal-filter-slot journal-filter-slot-date">
          <span className="journal-filter-inline-label">To Date</span>
          <input
            className="journal-filter-control"
            aria-label="Filter to date"
            type="date"
            value={filter.toDate}
            onChange={(e) => updateFilter({ toDate: e.target.value })}
          />
        </label>
        </div>
        <TableRowIconButton
          type="button"
          onClick={() => void openCreate()}
          disabled={accounts.length < 2}
          title="Add Journal Entry"
          aria-label="Add Journal Entry"
        >
          <NotebookPen size={18} strokeWidth={2} aria-hidden />
        </TableRowIconButton>
      </div>

      {presetsError && (
        <p className="error journal-presets-fetch-error" role="alert">
          {presetsError}
        </p>
      )}

      <dialog ref={saveDialogRef} aria-label="Save filter preset">
        <form method="dialog" onSubmit={(e) => void handleSavePreset(e)}>
          <h3>Save filter preset</h3>
          <label>
            Preset name
            <input
              aria-label="Preset name"
              type="text"
              value={saveName}
              autoFocus
              onChange={(e) => setSaveName(e.target.value)}
              required
              maxLength={200}
            />
          </label>
          {saveError && (
            <p className="error" role="alert">
              {saveError}
            </p>
          )}
          <div className="dialog-actions">
            <button
              type="button"
              className="button-secondary"
              onClick={() => setSaveDialogOpen(false)}
              disabled={savePending}
            >
              Cancel
            </button>
            <button type="submit" disabled={savePending}>
              {savePending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </dialog>

      {listLoading && entries.length === 0 && <p>Loading…</p>}
      {listError && (
        <p className="error" role="alert">
          {listError}
        </p>
      )}

      {!listError && entries.length === 0 && !listLoading && <p>No journal entries in this range.</p>}

      {entries.length > 0 && (
        <table className="journal-entry-list">
          <thead>
            <tr>
              <th>Date</th>
              <th>Summary</th>
              <th>Needs review</th>
              <th>Parties</th>
              <th>Debit account</th>
              <th>Credit account</th>
              <th className="journal-list-amount">Amount</th>
              <th aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {entries.map((row) => (
              <tr key={row.id}>
                <td>{row.entry_date}</td>
                <td>{row.summary}</td>
                <td>{row.requires_review ? "Yes" : "—"}</td>
                <td>{row.party_labels}</td>
                <td>{row.debit_side_label}</td>
                <td>{row.credit_side_label}</td>
                <td className="journal-list-amount">{row.amount}</td>
                <td>
                  <div className="journal-list-actions">
                    <TableRowIconButton
                      type="button"
                      onClick={() => void openEdit(row.id)}
                      title={`Edit journal entry: ${row.summary}`}
                      aria-label={`Edit journal entry: ${row.summary}`}
                    >
                      <Pencil size={18} strokeWidth={2} aria-hidden />
                    </TableRowIconButton>
                    <TableRowIconButton
                      type="button"
                      onClick={() => setAttachmentsEntryId(row.id)}
                      title={`Attachments for ${row.summary}`}
                      aria-label={`Attachments for ${row.summary}`}
                    >
                      <Paperclip size={18} strokeWidth={2} aria-hidden />
                    </TableRowIconButton>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {hasMore && (
        <button
          type="button"
          className="button-secondary"
          disabled={listLoading}
          onClick={() => void loadMore()}
        >
          {listLoading ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
    </>
  );
}
