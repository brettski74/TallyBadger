import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownNarrowWide,
  ArrowDownWideNarrow,
  Eye,
  FilePlus2,
  Pencil,
  RefreshCcw,
  SquareCheckBig,
  SquareX,
  Trash2,
} from "lucide-react";

import type { Account } from "../api/accounts";
import {
  createParty,
  listParties,
  listPartiesRegister,
  listPartySubtypeSuggestions,
  updateParty,
  type Party,
  type PartyActiveFilter,
  type PartyCreateInput,
  type PartyRole,
} from "../api/parties";
import { useFormSaveRevertShortcuts } from "../hooks/useFormSaveRevertShortcuts";
import { partyListParamsFromRegisterState } from "../lib/partyRegisterFilters";
import {
  discardActionTooltip,
  discardAriaKeyShortcuts,
  newActionTooltip,
  newAriaKeyShortcuts,
  newEntityAriaLabel,
  saveActionTooltip,
  saveAriaKeyShortcuts,
} from "../lib/keyboardHints";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";
import {
  PARTY_REGISTER_SORT_FIELDS,
  cycleSortKeys,
  primarySortKey,
  type PartyRegisterSortField,
  type PartySortKey,
} from "../lib/partyRegisterSort";
import { JournalFilterMultiDropdown } from "./JournalFilterMultiDropdown";
import { SubtypeCombobox } from "./SubtypeCombobox";
import { TableRowIconButton } from "./TableRowIconButton";

const PARTY_ROLES: PartyRole[] = ["customer", "vendor", "both", "other"];

const SUBTYPE_NULL_TOKEN = "__null__";

const DOCS_CEL_HINT =
  "Regex patterns are used by import CEL rules (party() function). See docs/cel-function-reference.md in the repo.";

const DEFAULT_SORT_KEYS: PartySortKey[] = [{ field: PARTY_REGISTER_SORT_FIELDS.name, direction: "asc" }];

type PartyFormSnapshot = {
  name: string;
  role: PartyRole;
  subtype: string;
  patterns: string[];
  defRev: string;
  defExp: string;
};

const EMPTY_CREATE_SNAPSHOT: PartyFormSnapshot = {
  name: "",
  role: "both",
  subtype: "",
  patterns: [],
  defRev: "",
  defExp: "",
};

function snapshotFromParty(party: Party): PartyFormSnapshot {
  return {
    name: party.name,
    role: party.role,
    subtype: party.subtype ?? "",
    patterns: party.match_patterns?.length ? [...party.match_patterns] : [],
    defRev: party.default_revenue_account_id != null ? String(party.default_revenue_account_id) : "",
    defExp: party.default_expense_account_id != null ? String(party.default_expense_account_id) : "",
  };
}

function revenuePickable(role: PartyRole): boolean {
  return role === "customer" || role === "both";
}

function expensePickable(role: PartyRole): boolean {
  return role === "vendor" || role === "both";
}

function PartySortableColumnHeader({
  label,
  field,
  sortKeys,
  onSort,
}: {
  label: string;
  field: PartyRegisterSortField;
  sortKeys: PartySortKey[];
  onSort: (field: PartyRegisterSortField) => void;
}) {
  const primary = primarySortKey(sortKeys);
  const isPrimary = primary?.field === field;
  const ariaSort = isPrimary
    ? primary.direction === "asc"
      ? "ascending"
      : "descending"
    : "none";
  const sortLabel = isPrimary
    ? `Sort by ${label}, ${primary.direction === "asc" ? "ascending" : "descending"}`
    : `Sort by ${label}`;

  return (
    <th aria-sort={ariaSort}>
      <button
        type="button"
        className="cheque-register-sort-header"
        onClick={() => onSort(field)}
        aria-label={sortLabel}
      >
        <span>{label}</span>
        {isPrimary && primary.direction === "asc" && (
          <ArrowDownNarrowWide size={16} strokeWidth={2} aria-hidden />
        )}
        {isPrimary && primary.direction === "desc" && (
          <ArrowDownWideNarrow size={16} strokeWidth={2} aria-hidden />
        )}
      </button>
    </th>
  );
}

interface PartiesSectionProps {
  accounts: Account[];
  onPartyCreated: (party: Party) => void;
  onPartyUpdated: (party: Party) => void;
}

export function PartiesSection({ accounts, onPartyCreated, onPartyUpdated }: PartiesSectionProps) {
  const [registerRows, setRegisterRows] = useState<Party[]>([]);
  const [registerLoading, setRegisterLoading] = useState(true);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [anyPartiesInDb, setAnyPartiesInDb] = useState<boolean | null>(null);

  const [filterName, setFilterName] = useState("");
  const [activeFilter, setActiveFilter] = useState<PartyActiveFilter>("active");
  const [selectedRoles, setSelectedRoles] = useState<PartyRole[]>([]);
  const [selectedSubtypes, setSelectedSubtypes] = useState<string[]>([]);
  const [sortKeys, setSortKeys] = useState<PartySortKey[]>(DEFAULT_SORT_KEYS);

  const [subtypeSuggestions, setSubtypeSuggestions] = useState<string[]>([]);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [editingPartyId, setEditingPartyId] = useState<number | null>(null);
  const [viewParty, setViewParty] = useState<Party | null>(null);

  const [createError, setCreateError] = useState<string | null>(null);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState<PartyRole>("both");
  const [subtype, setSubtype] = useState("");
  const [createPatterns, setCreatePatterns] = useState<string[]>([]);
  const [createDefRev, setCreateDefRev] = useState("");
  const [createDefExp, setCreateDefExp] = useState("");

  const [editError, setEditError] = useState<string | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState<PartyRole>("both");
  const [editSubtype, setEditSubtype] = useState("");
  const [editPatterns, setEditPatterns] = useState<string[]>([]);
  const [editDefRev, setEditDefRev] = useState("");
  const [editDefExp, setEditDefExp] = useState("");

  const [rowActionError, setRowActionError] = useState<string | null>(null);
  const [partyRowBusyId, setPartyRowBusyId] = useState<number | null>(null);

  const createFormRef = useRef<HTMLFormElement>(null);
  const editFormRef = useRef<HTMLFormElement>(null);
  const createDialogRef = useRef<HTMLDialogElement>(null);
  const editDialogRef = useRef<HTMLDialogElement>(null);
  const viewDialogRef = useRef<HTMLDialogElement>(null);
  const createNameInputRef = useRef<HTMLInputElement>(null);
  const editNameInputRef = useRef<HTMLInputElement>(null);
  const createPatternInputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const editPatternInputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const pendingPatternFocusRef = useRef<{ which: "create" | "edit"; index: number } | null>(null);
  const createFormBaselineRef = useRef<PartyFormSnapshot>(EMPTY_CREATE_SNAPSHOT);
  const editFormBaselineRef = useRef<PartyFormSnapshot | null>(null);

  const isMac = useMemo(() => isMacLikeUserAgent(), []);

  const listParams = useMemo(
    () =>
      partyListParamsFromRegisterState({
        filterName,
        activeFilter,
        selectedRoles,
        selectedSubtypes,
        sortKeys,
      }),
    [filterName, activeFilter, selectedRoles, selectedSubtypes, sortKeys],
  );

  const reloadRegister = useCallback(async () => {
    setRegisterError(null);
    setFilterError(null);
    setRegisterLoading(true);
    try {
      const rows = await listPartiesRegister(listParams);
      setRegisterRows(rows);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load parties";
      setRegisterRows([]);
      if (listParams.name) {
        setFilterError(message);
      } else {
        setRegisterError(message);
      }
    } finally {
      setRegisterLoading(false);
    }
  }, [listParams]);

  useEffect(() => {
    void reloadRegister();
  }, [reloadRegister]);

  useEffect(() => {
    void listParties()
      .then((rows) => setAnyPartiesInDb(rows.length > 0))
      .catch(() => setAnyPartiesInDb(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const s = await listPartySubtypeSuggestions();
        if (!cancelled) {
          setSubtypeSuggestions(s);
        }
      } catch {
        if (!cancelled) {
          setSubtypeSuggestions([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const subtypeFilterOptions = useMemo(
    () => [
      { id: SUBTYPE_NULL_TOKEN, label: "(no subtype)" },
      ...subtypeSuggestions.map((s) => ({ id: s, label: s })),
    ],
    [subtypeSuggestions],
  );

  const subtypeCandidates = useMemo(() => {
    const fromRows = registerRows.map((p) => p.subtype?.trim()).filter((s): s is string => Boolean(s));
    const seen = new Set<string>();
    const out: string[] = [];
    for (const s of [...subtypeSuggestions, ...fromRows]) {
      const key = s.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(s);
    }
    out.sort((a, b) => a.localeCompare(b));
    return out;
  }, [registerRows, subtypeSuggestions]);

  const revenueEquityAccounts = useMemo(
    () =>
      accounts
        .filter((a) => (a.type === "revenue" || a.type === "equity") && a.is_active)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [accounts],
  );
  const expenseAccounts = useMemo(
    () => accounts.filter((a) => a.type === "expense" && a.is_active).sort((a, b) => a.name.localeCompare(b.name)),
    [accounts],
  );

  const editingParty =
    editingPartyId != null ? registerRows.find((p) => p.id === editingPartyId) : undefined;

  const createPatternCount = createDialogOpen ? createPatterns.length : 0;
  const editPatternCount = editDialogOpen ? editPatterns.length : 0;
  const viewPatternCount = viewDialogOpen ? (viewParty?.match_patterns?.length ?? 0) : 0;
  const dialogPatternCount = Math.max(createPatternCount, editPatternCount, viewPatternCount);

  function applyCreateSnapshot(snapshot: PartyFormSnapshot) {
    setName(snapshot.name);
    setRole(snapshot.role);
    setSubtype(snapshot.subtype);
    setCreatePatterns(snapshot.patterns.length ? [...snapshot.patterns] : []);
    setCreateDefRev(snapshot.defRev);
    setCreateDefExp(snapshot.defExp);
    setCreateError(null);
  }

  function applyEditSnapshot(snapshot: PartyFormSnapshot) {
    setEditName(snapshot.name);
    setEditRole(snapshot.role);
    setEditSubtype(snapshot.subtype);
    setEditPatterns(snapshot.patterns.length ? [...snapshot.patterns] : []);
    setEditDefRev(snapshot.defRev);
    setEditDefExp(snapshot.defExp);
    setEditError(null);
  }

  function resetCreateForm() {
    applyCreateSnapshot(EMPTY_CREATE_SNAPSHOT);
    createFormBaselineRef.current = { ...EMPTY_CREATE_SNAPSHOT, patterns: [] };
  }

  function openCreateDialog() {
    resetCreateForm();
    setCreateDialogOpen(true);
  }

  function closeCreateDialog() {
    setCreateDialogOpen(false);
    setCreateError(null);
  }

  function startEdit(party: Party) {
    const snapshot = snapshotFromParty(party);
    editFormBaselineRef.current = snapshot;
    setEditingPartyId(party.id);
    applyEditSnapshot(snapshot);
    setRowActionError(null);
    setEditDialogOpen(true);
  }

  function closeEditDialog() {
    setEditDialogOpen(false);
    setEditingPartyId(null);
    setEditError(null);
  }

  function openView(party: Party) {
    setViewParty(party);
    setViewDialogOpen(true);
  }

  function closeViewDialog() {
    setViewDialogOpen(false);
    setViewParty(null);
  }

  const handleSortColumn = useCallback((field: PartyRegisterSortField) => {
    setSortKeys((current) => cycleSortKeys(current, field));
  }, []);

  useEffect(() => {
    const el = createDialogRef.current;
    if (!el) return;
    if (createDialogOpen && !el.open) {
      el.showModal();
      queueMicrotask(() => createNameInputRef.current?.focus());
    } else if (!createDialogOpen && el.open) el.close();
  }, [createDialogOpen]);

  useEffect(() => {
    const el = editDialogRef.current;
    if (!el) return;
    if (editDialogOpen && !el.open) {
      el.showModal();
      queueMicrotask(() => editNameInputRef.current?.focus());
    } else if (!editDialogOpen && el.open) el.close();
  }, [editDialogOpen]);

  useEffect(() => {
    const pending = pendingPatternFocusRef.current;
    if (!pending) return;
    pendingPatternFocusRef.current = null;
    const refs = pending.which === "create" ? createPatternInputRefs : editPatternInputRefs;
    queueMicrotask(() => refs.current[pending.index]?.focus());
  }, [createPatterns, editPatterns]);

  useEffect(() => {
    const el = viewDialogRef.current;
    if (!el) return;
    if (viewDialogOpen && !el.open) el.showModal();
    else if (!viewDialogOpen && el.open) el.close();
  }, [viewDialogOpen]);

  const modalOpen = createDialogOpen || editDialogOpen || viewDialogOpen;

  useFormSaveRevertShortcuts({
    createFormRef,
    editFormRef,
    editingId: editingPartyId,
    createDialogActive: createDialogOpen,
    viewDialogActive: viewDialogOpen,
    canSubmitCreate: name.trim().length > 0,
    canSubmitEdit: editName.trim().length > 0,
    createSubmitting,
    editSubmitting,
    requestCreateSubmit: () => createFormRef.current?.requestSubmit(),
    requestEditSubmit: () => editFormRef.current?.requestSubmit(),
    requestCreateRevert: () => applyCreateSnapshot(createFormBaselineRef.current),
    requestEditRevert: () => {
      if (editFormBaselineRef.current) {
        applyEditSnapshot(editFormBaselineRef.current);
      }
    },
    requestCreateClose: closeCreateDialog,
    requestEditClose: closeEditDialog,
    requestViewClose: closeViewDialog,
    escapeActive: modalOpen,
    requestNew: openCreateDialog,
    newShortcutActive: !modalOpen,
  });

  async function patchPartyActive(party: Party, nextActive: boolean) {
    setRowActionError(null);
    setPartyRowBusyId(party.id);
    try {
      const updated = await updateParty(party.id, { is_active: nextActive });
      onPartyUpdated(updated);
      await reloadRegister();
    } catch (err) {
      setRowActionError(err instanceof Error ? err.message : "Failed to update party");
    } finally {
      setPartyRowBusyId(null);
    }
  }

  function tryDeactivateParty(party: Party) {
    const msg = `Deactivate party "${party.name}"? It will stay on existing journal links but won't appear in pickers for new associations.`;
    if (!window.confirm(msg)) {
      return;
    }
    void patchPartyActive(party, false);
  }

  function tryReactivateParty(party: Party) {
    void patchPartyActive(party, true);
  }

  function setPatternAt(which: "create" | "edit", index: number, value: string) {
    if (which === "create") {
      setCreatePatterns((prev) => prev.map((p, i) => (i === index ? value : p)));
    } else {
      setEditPatterns((prev) => prev.map((p, i) => (i === index ? value : p)));
    }
  }

  function addPatternRow(which: "create" | "edit") {
    if (which === "create") {
      setCreatePatterns((prev) => {
        pendingPatternFocusRef.current = { which: "create", index: prev.length };
        return [...prev, ""];
      });
    } else {
      setEditPatterns((prev) => {
        pendingPatternFocusRef.current = { which: "edit", index: prev.length };
        return [...prev, ""];
      });
    }
  }

  function removePatternRow(which: "create" | "edit", index: number) {
    if (which === "create") {
      setCreatePatterns((prev) => prev.filter((_, i) => i !== index));
    } else {
      setEditPatterns((prev) => prev.filter((_, i) => i !== index));
    }
  }

  function buildPayloadFromForm(
    form: PartyFormSnapshot,
    forCreate: boolean,
  ): PartyCreateInput | Parameters<typeof updateParty>[1] {
    const patterns = form.patterns.map((p) => p.trim()).filter(Boolean);
    const base = {
      name: form.name.trim(),
      role: form.role,
      match_patterns: patterns,
      subtype: form.subtype.trim() ? form.subtype.trim() : null,
      default_revenue_account_id: null as number | null,
      default_expense_account_id: null as number | null,
    };
    if (revenuePickable(form.role) && form.defRev) {
      base.default_revenue_account_id = Number(form.defRev);
    }
    if (expensePickable(form.role) && form.defExp) {
      base.default_expense_account_id = Number(form.defExp);
    }
    if (forCreate) {
      return { ...base, is_active: true };
    }
    return base;
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);
    if (!name.trim()) {
      setCreateError("Party name is required");
      return;
    }
    setCreateSubmitting(true);
    try {
      const payload = buildPayloadFromForm(
        {
          name,
          role,
          subtype,
          patterns: createPatterns,
          defRev: createDefRev,
          defExp: createDefExp,
        },
        true,
      ) as PartyCreateInput;
      const created = await createParty(payload);
      onPartyCreated(created);
      closeCreateDialog();
      resetCreateForm();
      await reloadRegister();
      setAnyPartiesInDb(true);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create party");
    } finally {
      setCreateSubmitting(false);
    }
  }

  async function handleEditSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editingPartyId == null) {
      return;
    }
    setEditError(null);
    if (!editName.trim()) {
      setEditError("Party name is required");
      return;
    }
    setEditSubmitting(true);
    try {
      const patch = buildPayloadFromForm(
        {
          name: editName,
          role: editRole,
          subtype: editSubtype,
          patterns: editPatterns,
          defRev: editDefRev,
          defExp: editDefExp,
        },
        false,
      );
      const updated = await updateParty(editingPartyId, patch);
      onPartyUpdated(updated);
      closeEditDialog();
      await reloadRegister();
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update party");
    } finally {
      setEditSubmitting(false);
    }
  }

  function renderPartyFields(
    mode: "create" | "edit" | "view",
    party?: Party,
  ) {
    const readOnly = mode === "view";
    const formName = mode === "create" ? name : mode === "edit" ? editName : party?.name ?? "";
    const formRole = mode === "create" ? role : mode === "edit" ? editRole : party?.role ?? "both";
    const formSubtype =
      mode === "create" ? subtype : mode === "edit" ? editSubtype : party?.subtype ?? "";
    const formPatterns =
      mode === "create"
        ? createPatterns
        : mode === "edit"
          ? editPatterns
          : party?.match_patterns ?? [];
    const formDefRev =
      mode === "create" ? createDefRev : mode === "edit" ? editDefRev : party?.default_revenue_account_id != null
        ? String(party.default_revenue_account_id)
        : "";
    const formDefExp =
      mode === "create" ? createDefExp : mode === "edit" ? editDefExp : party?.default_expense_account_id != null
        ? String(party.default_expense_account_id)
        : "";
    const statusLabel =
      mode === "view"
        ? party?.is_active
          ? "active"
          : "inactive"
        : mode === "edit"
          ? editingParty?.is_active
            ? "active"
            : "inactive"
          : "active";

    const setNameFn = mode === "create" ? setName : setEditName;
    const setRoleFn = mode === "create" ? setRole : setEditRole;
    const setSubtypeFn = mode === "create" ? setSubtype : setEditSubtype;

    return (
      <>
        <div className="cheque-form-grid">
          <div className="cheque-form-col">
            <label>
              Name
              <input
                ref={mode === "create" ? createNameInputRef : mode === "edit" ? editNameInputRef : undefined}
                aria-label={mode === "create" ? "Party name" : mode === "edit" ? "Edit party name" : "Party name"}
                value={formName}
                onChange={readOnly ? undefined : (e) => setNameFn(e.target.value)}
                readOnly={readOnly}
                placeholder={mode === "create" ? "e.g. Acme Yard Maintenance" : undefined}
              />
            </label>
            <label>
              Role
              {readOnly ? (
                <input aria-label="Party role" value={formRole} readOnly />
              ) : (
                <select
                  aria-label={mode === "create" ? "Party role" : "Edit party role"}
                  value={formRole}
                  onChange={(e) => setRoleFn(e.target.value as PartyRole)}
                >
                  {PARTY_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              )}
            </label>
            <label>
              Subtype (optional)
              {readOnly ? (
                <input aria-label="Party subtype" value={formSubtype || "—"} readOnly />
              ) : (
                <SubtypeCombobox
                  aria-label={mode === "create" ? "Party subtype" : "Edit party subtype"}
                  value={formSubtype}
                  onChange={setSubtypeFn}
                  suggestions={subtypeCandidates}
                  placeholder="e.g. Tenant, Utilities"
                />
              )}
            </label>
          </div>
          <div className="cheque-form-col">
            <label>
              Status
              <input aria-label="Party status" value={statusLabel} readOnly tabIndex={-1} />
            </label>
            {revenuePickable(formRole) && (
              <label>
                Default revenue / equity account{mode === "create" ? " (optional)" : ""}
                {readOnly ? (
                  <input
                    aria-label="Default revenue or equity account"
                    value={
                      party?.default_revenue_account_name ? `${party.default_revenue_account_name}` : "—"
                    }
                    readOnly
                  />
                ) : (
                  <select
                    aria-label={
                      mode === "create"
                        ? "Default revenue or equity account"
                        : "Edit default revenue or equity account"
                    }
                    value={formDefRev}
                    onChange={(e) =>
                      mode === "create" ? setCreateDefRev(e.target.value) : setEditDefRev(e.target.value)
                    }
                  >
                    <option value="">— none —</option>
                    {revenueEquityAccounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.type})
                      </option>
                    ))}
                  </select>
                )}
              </label>
            )}
            {expensePickable(formRole) && (
              <label>
                Default expense account{mode === "create" ? " (optional)" : ""}
                {readOnly ? (
                  <input
                    aria-label="Default expense account"
                    value={party?.default_expense_account_name ? `${party.default_expense_account_name}` : "—"}
                    readOnly
                  />
                ) : (
                  <select
                    aria-label={mode === "create" ? "Default expense account" : "Edit default expense account"}
                    value={formDefExp}
                    onChange={(e) =>
                      mode === "create" ? setCreateDefExp(e.target.value) : setEditDefExp(e.target.value)
                    }
                  >
                    <option value="">— none —</option>
                    {expenseAccounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.type})
                      </option>
                    ))}
                  </select>
                )}
              </label>
            )}
          </div>
        </div>

        <fieldset style={{ width: "100%", minWidth: 0 }}>
          <legend>Match patterns{mode === "create" ? " (optional)" : ""}</legend>
          <p className="muted" style={{ marginTop: 0 }}>
            {DOCS_CEL_HINT}
          </p>
          {readOnly ? (
            formPatterns.length > 0 ? (
              <ul className="party-pattern-list party-pattern-list--view">
                {formPatterns.map((pat, index) => (
                  <li key={`view-pat-${index}`} className="party-pattern-row">
                    <span className="party-pattern-index" aria-hidden>
                      {index + 1}:
                    </span>
                    <span className="party-pattern-view-value">{pat}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">—</p>
            )
          ) : (
            <>
              <div className="party-pattern-list">
                {formPatterns.map((pat, index) => (
                  <div key={`${mode}-pat-${index}`} className="party-pattern-row">
                    <span className="party-pattern-index" aria-hidden>
                      {index + 1}:
                    </span>
                    <input
                      ref={(el) => {
                        if (mode === "create") {
                          createPatternInputRefs.current[index] = el;
                        } else {
                          editPatternInputRefs.current[index] = el;
                        }
                      }}
                      aria-label={`${mode === "create" ? "Create" : "Edit"} match pattern ${index + 1}`}
                      value={pat}
                      onChange={(e) => setPatternAt(mode, index, e.target.value)}
                      placeholder="Python re.search regex"
                    />
                    <TableRowIconButton
                      type="button"
                      aria-label={`Remove match pattern ${index + 1}`}
                      title={`Remove match pattern ${index + 1}`}
                      onClick={() => removePatternRow(mode, index)}
                    >
                      <Trash2 size={18} strokeWidth={2} aria-hidden />
                    </TableRowIconButton>
                  </div>
                ))}
              </div>
              <button type="button" className="button-secondary" onClick={() => addPatternRow(mode)}>
                Add pattern
              </button>
            </>
          )}
        </fieldset>
      </>
    );
  }

  const emptyMessage =
    anyPartiesInDb === false ? "No parties yet." : "No parties match these filters.";

  const dialogClass =
    dialogPatternCount >= 3
      ? "cheque-dialog party-dialog party-dialog-many-patterns"
      : "cheque-dialog party-dialog";

  return (
    <>
      <section className="card journal-card-wide">
        <div className="cheque-register-toolbar">
          <h2>Parties</h2>
          <div className="cheque-register-actions">
            <TableRowIconButton
              type="button"
              aria-label="Refresh list"
              title="Refresh list"
              disabled={registerLoading}
              onClick={() => void reloadRegister()}
            >
              <RefreshCcw size={18} strokeWidth={2} aria-hidden />
            </TableRowIconButton>
            <TableRowIconButton
              type="button"
              aria-label={newEntityAriaLabel("New party", isMac)}
              title={newActionTooltip(isMac)}
              aria-keyshortcuts={newAriaKeyShortcuts(isMac)}
              onClick={openCreateDialog}
            >
              <FilePlus2 size={18} strokeWidth={2} aria-hidden />
            </TableRowIconButton>
          </div>
        </div>
        <p className="muted">Filter by name (regex), active status, role, or subtype.</p>

        <div className="cheque-register-filters">
          <label>
            Name
            <input
              type="search"
              value={filterName}
              onChange={(e) => setFilterName(e.target.value)}
              aria-label="Filter parties by name"
              placeholder="Regex on name"
              className="journal-filter-control"
            />
          </label>
          <label>
            Active
            <select
              value={activeFilter}
              onChange={(e) => setActiveFilter(e.target.value as PartyActiveFilter)}
              aria-label="Filter parties by active status"
              className="journal-filter-control"
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="all">All</option>
            </select>
          </label>
          <JournalFilterMultiDropdown<PartyRole>
            label="Role"
            ariaFilterLabel="Filter parties by role"
            options={PARTY_ROLES.map((r) => ({ id: r, name: r }))}
            selectedIds={selectedRoles}
            onIdsChange={setSelectedRoles}
          />
          <JournalFilterMultiDropdown
            label="Subtype"
            ariaFilterLabel="Filter parties by subtype"
            options={subtypeFilterOptions.map((o) => ({ id: o.id, name: o.label }))}
            selectedIds={selectedSubtypes}
            onIdsChange={setSelectedSubtypes}
          />
        </div>

        {filterError && <p className="error-text">{filterError}</p>}
        {registerError && (
          <p className="error" role="alert">
            {registerError}
          </p>
        )}
        {rowActionError && (
          <p className="error" role="alert">
            {rowActionError}
          </p>
        )}

        <div style={{ overflowX: "auto" }}>
          <table aria-label="Parties register">
            <thead>
              <tr>
                <PartySortableColumnHeader
                  label="Name"
                  field={PARTY_REGISTER_SORT_FIELDS.name}
                  sortKeys={sortKeys}
                  onSort={handleSortColumn}
                />
                <PartySortableColumnHeader
                  label="Role"
                  field={PARTY_REGISTER_SORT_FIELDS.role}
                  sortKeys={sortKeys}
                  onSort={handleSortColumn}
                />
                <PartySortableColumnHeader
                  label="Subtype"
                  field={PARTY_REGISTER_SORT_FIELDS.subtype}
                  sortKeys={sortKeys}
                  onSort={handleSortColumn}
                />
                <th>Patterns</th>
                <PartySortableColumnHeader
                  label="Status"
                  field={PARTY_REGISTER_SORT_FIELDS.isActive}
                  sortKeys={sortKeys}
                  onSort={handleSortColumn}
                />
                <th className="table-row-actions-heading" aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {registerLoading && registerRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    Loading…
                  </td>
                </tr>
              ) : registerRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    {emptyMessage}
                  </td>
                </tr>
              ) : (
                registerRows.map((party) => {
                  const rowActionsLocked = partyRowBusyId !== null;
                  return (
                    <tr key={party.id}>
                      <td>{party.name}</td>
                      <td>{party.role}</td>
                      <td>{party.subtype ?? "—"}</td>
                      <td>{party.match_patterns?.length ? `${party.match_patterns.length} regex` : "—"}</td>
                      <td>{party.is_active ? "active" : "inactive"}</td>
                      <td className="table-row-actions-cell">
                        <div
                          className="table-row-actions"
                          role="group"
                          aria-label={`Actions for party ${party.name}`}
                        >
                          {party.is_active ? (
                            <>
                              <TableRowIconButton
                                aria-label={`Edit party ${party.name}`}
                                title={`Edit party ${party.name}`}
                                disabled={rowActionsLocked}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  startEdit(party);
                                }}
                              >
                                <Pencil size={18} strokeWidth={2} aria-hidden />
                              </TableRowIconButton>
                              <TableRowIconButton
                                aria-label={`Deactivate party ${party.name}`}
                                title={`Deactivate party ${party.name}`}
                                disabled={rowActionsLocked}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  tryDeactivateParty(party);
                                }}
                              >
                                <SquareX size={18} strokeWidth={2} aria-hidden />
                              </TableRowIconButton>
                            </>
                          ) : (
                            <>
                              <TableRowIconButton
                                aria-label={`View party ${party.name}`}
                                title={`View party ${party.name}`}
                                disabled={rowActionsLocked}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openView(party);
                                }}
                              >
                                <Eye size={18} strokeWidth={2} aria-hidden />
                              </TableRowIconButton>
                              <TableRowIconButton
                                aria-label={`Reactivate party ${party.name}`}
                                title={`Reactivate party ${party.name}`}
                                disabled={rowActionsLocked}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  tryReactivateParty(party);
                                }}
                              >
                                <SquareCheckBig size={18} strokeWidth={2} aria-hidden />
                              </TableRowIconButton>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      <dialog
        ref={createDialogRef}
        className={dialogClass}
        aria-labelledby="party-create-title"
        onClose={closeCreateDialog}
      >
        <div className="cheque-dialog-inner">
          <div className="cheque-dialog-header">
            <h2 id="party-create-title">Create party</h2>
            <button type="button" className="button-secondary" onClick={closeCreateDialog}>
              Close
            </button>
          </div>
          <p className="muted">
            Tenants, vendors, or both (e.g. a tenant who also invoices you). Parties can be linked on journal
            lines.
          </p>
          <form ref={createFormRef} onSubmit={(e) => void handleCreate(e)}>
            {renderPartyFields("create")}
            <div className="dialog-actions">
              <button type="button" className="button-secondary" onClick={closeCreateDialog}>
                Cancel
              </button>
              <button
                disabled={createSubmitting}
                type="submit"
                title={saveActionTooltip(isMac)}
                aria-label={isMac ? "Create party (⌘+S)" : "Create party (Ctrl+S)"}
                aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
              >
                {createSubmitting ? "Creating…" : "Create party"}
              </button>
            </div>
            {createError && (
              <p className="error" role="alert">
                {createError}
              </p>
            )}
          </form>
        </div>
      </dialog>

      <dialog
        ref={editDialogRef}
        className={dialogClass}
        aria-labelledby="party-edit-title"
        onClose={closeEditDialog}
      >
        <div className="cheque-dialog-inner">
          <div className="cheque-dialog-header">
            <h2 id="party-edit-title">Edit party</h2>
            <button type="button" className="button-secondary" onClick={closeEditDialog}>
              Close
            </button>
          </div>
          <form ref={editFormRef} onSubmit={(e) => void handleEditSave(e)}>
            {renderPartyFields("edit")}
            <div className="dialog-actions">
              <button type="button" className="button-secondary" onClick={closeEditDialog}>
                Cancel
              </button>
              <button
                disabled={editSubmitting}
                type="submit"
                title={saveActionTooltip(isMac)}
                aria-label={isMac ? "Save changes (⌘+S)" : "Save changes (Ctrl+S)"}
                aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
              >
                {editSubmitting ? "Saving…" : "Save changes"}
              </button>
              <button
                type="button"
                className="button-secondary"
                title={discardActionTooltip(isMac)}
                aria-label={discardActionTooltip(isMac)}
                aria-keyshortcuts={discardAriaKeyShortcuts(isMac)}
                onClick={() => {
                  if (editFormBaselineRef.current) {
                    applyEditSnapshot(editFormBaselineRef.current);
                  }
                }}
              >
                Discard
              </button>
            </div>
            {editError && (
              <p className="error" role="alert">
                {editError}
              </p>
            )}
          </form>
        </div>
      </dialog>

      <dialog
        ref={viewDialogRef}
        className={dialogClass}
        aria-labelledby="party-view-title"
        onClose={closeViewDialog}
      >
        <div className="cheque-dialog-inner">
          <div className="cheque-dialog-header">
            <h2 id="party-view-title">View party</h2>
            <button type="button" className="button-secondary" onClick={closeViewDialog}>
              Close
            </button>
          </div>
          {viewParty && renderPartyFields("view", viewParty)}
          <div className="dialog-actions">
            <button type="button" className="button-secondary" onClick={closeViewDialog}>
              Close
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}
