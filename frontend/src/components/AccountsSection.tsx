import type { CSSProperties } from "react";
import { FormEvent, Fragment, useMemo, useRef, useState } from "react";
import { FilePlus, Pencil, Save, SquareCheckBig, SquareX, Undo2 } from "lucide-react";

import {
  Account,
  AccountType,
  createAccount,
  updateAccount,
  UpdateAccountInput,
} from "../api/accounts";
import { useFormSaveRevertShortcuts } from "../hooks/useFormSaveRevertShortcuts";
import {
  newActionTooltip,
  newAriaKeyShortcuts,
  newEntityAriaLabel,
  discardActionTooltip,
  discardAriaKeyShortcuts,
  saveActionTooltip,
  saveAriaKeyShortcuts,
} from "../lib/keyboardHints";
import { accountNameMatchesGlob } from "../lib/accountNameGlob";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";
import { JournalFilterMultiDropdown } from "./JournalFilterMultiDropdown";
import { TableRowIconButton } from "./TableRowIconButton";

const ACCOUNT_TYPES: AccountType[] = ["asset", "liability", "equity", "revenue", "expense", "suspense"];

type ActiveVisibility = "active" | "inactive" | "all";

const ACCOUNT_TYPE_FILTER_OPTIONS = ACCOUNT_TYPES.map((name, id) => ({ id, name }));

function accountMatchesListFilters(
  account: Account,
  namePattern: string,
  typeFilterIds: number[],
  activeVisibility: ActiveVisibility,
): boolean {
  if (activeVisibility === "active" && !account.is_active) {
    return false;
  }
  if (activeVisibility === "inactive" && account.is_active) {
    return false;
  }
  if (typeFilterIds.length > 0) {
    const idx = ACCOUNT_TYPES.indexOf(account.type);
    if (!typeFilterIds.includes(idx)) {
      return false;
    }
  }
  const trimmed = namePattern.trim();
  if (trimmed !== "" && !accountNameMatchesGlob(account.name, trimmed)) {
    return false;
  }
  return true;
}

const CREATE_FORM_ID = "accounts-inline-create";
const EDIT_FORM_ID = "accounts-inline-edit";

const RENAME_CEL_WARNING =
  "Renaming an account can break CEL rules, import templates, or other text that matched the old name. " +
  "Only continue if you have checked those references (or enjoy surprise import failures — we don't judge, much). Continue anyway?";

const TYPE_CHANGE_CONFIRM =
  "Changing an account's type is unusual — reports and rules may have filed this under the old label. " +
  "Continue only if the original pick was genuinely wrong. Proceed anyway?";

const draftActiveBtnWrap: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "0.35rem",
  flexWrap: "wrap",
};

/** Row state uses numeric ids; coerce in case JSON ever delivers strings. */
function rowIdOf(account: Pick<Account, "id">): number {
  return Number(account.id);
}

interface AccountsSectionProps {
  accounts: Account[];
  loading: boolean;
  error: string | null;
  onAccountCreated: (account: Account) => void;
  onAccountUpdated: (account: Account) => void;
}

export function AccountsSection({
  accounts,
  loading,
  error,
  onAccountCreated,
  onAccountUpdated,
}: AccountsSectionProps) {
  const createFormRef = useRef<HTMLFormElement>(null);
  const editFormRef = useRef<HTMLFormElement>(null);
  /** Ignore Revert clicks for a beat after opening edit (stray completion click can land on Revert). */
  const suppressRevertUntilRef = useRef(0);

  const [isCreating, setIsCreating] = useState(false);
  const [createDraftName, setCreateDraftName] = useState("");
  const [createDraftType, setCreateDraftType] = useState<AccountType>("asset");
  const [createDraftActive, setCreateDraftActive] = useState(true);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createSubmitting, setCreateSubmitting] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftType, setDraftType] = useState<AccountType>("asset");
  const [draftActive, setDraftActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);

  const [rowActionError, setRowActionError] = useState<string | null>(null);
  const [accountRowBusyId, setAccountRowBusyId] = useState<number | null>(null);

  const [namePattern, setNamePattern] = useState("");
  const [typeFilterIds, setTypeFilterIds] = useState<number[]>([]);
  const [activeVisibility, setActiveVisibility] = useState<ActiveVisibility>("active");

  const isMac = useMemo(() => isMacLikeUserAgent(), []);

  const displayAccounts = useMemo(
    () =>
      accounts.filter(
        (a) =>
          accountMatchesListFilters(a, namePattern, typeFilterIds, activeVisibility) ||
          (editingId !== null && rowIdOf(a) === editingId),
      ),
    [accounts, namePattern, typeFilterIds, activeVisibility, editingId],
  );

  function closeInlineCreate() {
    setIsCreating(false);
    setCreateDraftName("");
    setCreateDraftType("asset");
    setCreateDraftActive(true);
    setCreateError(null);
    setCreateSubmitting(false);
  }

  function revertInlineCreate() {
    setCreateDraftName("");
    setCreateDraftType("asset");
    setCreateDraftActive(true);
    setCreateError(null);
  }

  function closeEdit() {
    setEditingId(null);
    setEditError(null);
  }

  function revertEdit(account: Account) {
    setDraftName(account.name);
    setDraftType(account.type);
    setDraftActive(account.is_active);
    setEditError(null);
  }

  function startCreate() {
    if (isCreating) {
      closeInlineCreate();
    }
    if (editingId !== null) {
      closeEdit();
    }
    setIsCreating(true);
    setCreateDraftName("");
    setCreateDraftType("asset");
    setCreateDraftActive(true);
    setCreateError(null);
    setRowActionError(null);
  }

  function startEdit(account: Account) {
    const rowId = rowIdOf(account);
    if (!Number.isFinite(rowId)) {
      return;
    }
    if (isCreating) {
      closeInlineCreate();
    }
    if (editingId !== null && editingId !== rowId) {
      closeEdit();
    }
    setEditingId(rowId);
    setDraftName(account.name);
    setDraftType(account.type);
    setDraftActive(account.is_active);
    setEditError(null);
    setRowActionError(null);
  }

  useFormSaveRevertShortcuts({
    createFormRef,
    editFormRef,
    editingId,
    inlineCreateActive: isCreating,
    canSubmitCreate: createDraftName.trim().length > 0,
    canSubmitEdit: draftName.trim().length > 0 && editingId !== null,
    createSubmitting,
    editSubmitting,
    requestCreateSubmit: () => {
      createFormRef.current?.requestSubmit();
    },
    requestEditSubmit: () => {
      editFormRef.current?.requestSubmit();
    },
    requestEditRevert: () => {
      const account = accounts.find((a) => rowIdOf(a) === editingId);
      if (account) {
        revertEdit(account);
      }
    },
    requestCreateRevert: revertInlineCreate,
    requestEditClose: closeEdit,
    requestCreateClose: closeInlineCreate,
    escapeActive: isCreating || editingId !== null,
    requestNew: startCreate,
    newShortcutActive: !isCreating,
  });

  async function patchAccountActive(account: Account, nextActive: boolean) {
    setRowActionError(null);
    setAccountRowBusyId(rowIdOf(account));
    try {
      const updated = await updateAccount(account.id, { is_active: nextActive });
      onAccountUpdated(updated);
    } catch (err) {
      setRowActionError(err instanceof Error ? err.message : "Failed to update account");
    } finally {
      setAccountRowBusyId(null);
    }
  }

  function tryDeactivateAccount(account: Account) {
    const msg = `Deactivate account "${account.name}"? It will stay on existing journal links but won't appear in pickers for new associations.`;
    if (!window.confirm(msg)) {
      return;
    }
    void patchAccountActive(account, false);
  }

  function tryReactivateAccount(account: Account) {
    void patchAccountActive(account, true);
  }

  function tryDeactivateDraft(setActive: (v: boolean) => void, label: string) {
    const msg = `Mark "${label}" inactive in this draft? It will be saved as inactive when you save.`;
    if (!window.confirm(msg)) {
      return;
    }
    setActive(false);
  }

  async function handleCreateSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);
    const trimmed = createDraftName.trim();
    if (!trimmed) {
      setCreateError("Account name is required");
      return;
    }
    setCreateSubmitting(true);
    try {
      const created = await createAccount({
        name: trimmed,
        type: createDraftType,
        is_active: createDraftActive,
      });
      onAccountCreated(created);
      closeInlineCreate();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create account");
    } finally {
      setCreateSubmitting(false);
    }
  }

  async function handleEditSubmit(event: FormEvent<HTMLFormElement>, original: Account) {
    event.preventDefault();
    setEditError(null);
    const trimmed = draftName.trim();
    if (!trimmed) {
      setEditError("Account name is required");
      return;
    }
    if (trimmed !== original.name) {
      if (!window.confirm(RENAME_CEL_WARNING)) {
        return;
      }
    }
    if (draftType !== original.type) {
      if (!window.confirm(TYPE_CHANGE_CONFIRM)) {
        return;
      }
    }

    const body: UpdateAccountInput = {};
    if (trimmed !== original.name) {
      body.name = trimmed;
    }
    if (draftActive !== original.is_active) {
      body.is_active = draftActive;
    }
    if (draftType !== original.type) {
      body.type = draftType;
    }

    if (Object.keys(body).length === 0) {
      closeEdit();
      return;
    }

    setEditSubmitting(true);
    try {
      const updated = await updateAccount(original.id, body);
      onAccountUpdated(updated);
      closeEdit();
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update account");
    } finally {
      setEditSubmitting(false);
    }
  }

  function renderDraftActiveCell(
    active: boolean,
    setActive: (v: boolean) => void,
    busy: boolean,
    contextLabel: string,
  ) {
    return (
      <div style={draftActiveBtnWrap}>
        {active ? (
          <TableRowIconButton
            aria-label={`Mark inactive in draft (${contextLabel})`}
            title="Mark inactive (confirm)"
            disabled={busy}
            onClick={() => tryDeactivateDraft(setActive, contextLabel)}
          >
            <SquareX size={18} strokeWidth={2} aria-hidden />
          </TableRowIconButton>
        ) : (
          <TableRowIconButton
            aria-label={`Mark active in draft (${contextLabel})`}
            title="Mark active"
            disabled={busy}
            onClick={() => setActive(true)}
          >
            <SquareCheckBig size={18} strokeWidth={2} aria-hidden />
          </TableRowIconButton>
        )}
      </div>
    );
  }

  return (
    <section className="card journal-card-wide accounts-panel">
      <div className="journal-list-toolbar journal-list-toolbar-with-filters">
        <h2>Accounts</h2>
        <div className="journal-filters-line">
          <label className="journal-filter-slot journal-filter-slot-select">
            <span className="journal-filter-inline-label">Name</span>
            <input
              type="text"
              className="journal-filter-control"
              aria-label="Filter accounts by name (glob: use * and ? as wildcards)"
              value={namePattern}
              onChange={(e) => setNamePattern(e.target.value)}
              placeholder="e.g. Cash*"
            />
          </label>
          <JournalFilterMultiDropdown
            label="Type"
            ariaFilterLabel="Filter accounts by type"
            options={ACCOUNT_TYPE_FILTER_OPTIONS}
            selectedIds={typeFilterIds}
            onIdsChange={setTypeFilterIds}
          />
          <label className="journal-filter-slot journal-filter-slot-select">
            <span className="journal-filter-inline-label">Active</span>
            <select
              className="journal-filter-control"
              aria-label="Filter accounts by active status"
              value={activeVisibility}
              onChange={(e) => setActiveVisibility(e.target.value as ActiveVisibility)}
            >
              <option value="active">Active only</option>
              <option value="inactive">Inactive only</option>
              <option value="all">All</option>
            </select>
          </label>
        </div>
        <TableRowIconButton
          type="button"
          onClick={startCreate}
          title={newActionTooltip(isMac)}
          aria-label={newEntityAriaLabel("Create account", isMac)}
          aria-keyshortcuts={newAriaKeyShortcuts(isMac)}
        >
          <FilePlus size={18} strokeWidth={2} aria-hidden />
        </TableRowIconButton>
      </div>

      {loading && <p>Loading accounts...</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {rowActionError && (
        <p className="error" role="alert">
          {rowActionError}
        </p>
      )}
      {!loading && !error && accounts.length === 0 && !isCreating && <p>No accounts yet.</p>}

      {!loading && !error && (accounts.length > 0 || isCreating) && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Status</th>
              <th className="table-row-actions-heading" aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {isCreating && (
              <Fragment key="__inline-create-block__">
                <tr>
                  <td>
                    <form
                      ref={createFormRef}
                      id={CREATE_FORM_ID}
                      aria-label="Create new account"
                      onSubmit={(e) => void handleCreateSubmit(e)}
                      hidden
                    />
                    <input
                      form={CREATE_FORM_ID}
                      aria-label="New account name"
                      value={createDraftName}
                      onChange={(e) => setCreateDraftName(e.target.value)}
                      placeholder="e.g. Cash"
                    />
                  </td>
                  <td>
                    <select
                      form={CREATE_FORM_ID}
                      aria-label="New account type"
                      value={createDraftType}
                      onChange={(e) => setCreateDraftType(e.target.value as AccountType)}
                    >
                      {ACCOUNT_TYPES.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {renderDraftActiveCell(
                      createDraftActive,
                      setCreateDraftActive,
                      createSubmitting,
                      createDraftName.trim() || "New account",
                    )}
                  </td>
                  <td className="table-row-actions-cell">
                    <div className="form-actions-inline">
                      <TableRowIconButton
                        type="submit"
                        form={CREATE_FORM_ID}
                        aria-label={isMac ? "Save new account (⌘+S)" : "Save new account (Ctrl+S)"}
                        title={saveActionTooltip(isMac)}
                        aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
                        disabled={createSubmitting}
                      >
                        <Save size={18} strokeWidth={2} aria-hidden />
                      </TableRowIconButton>
                      <TableRowIconButton
                        type="button"
                        className="button-secondary"
                        aria-label={discardActionTooltip(isMac)}
                        title={discardActionTooltip(isMac)}
                        aria-keyshortcuts={discardAriaKeyShortcuts(isMac)}
                        disabled={createSubmitting}
                        onClick={revertInlineCreate}
                      >
                        <Undo2 size={18} strokeWidth={2} aria-hidden />
                      </TableRowIconButton>
                    </div>
                  </td>
                </tr>
                <tr
                  className={
                    createError
                      ? "accounts-inline-feedback-row"
                      : "accounts-inline-feedback-row accounts-inline-feedback-row--empty"
                  }
                  aria-hidden={!createError}
                >
                  <td colSpan={4}>
                    <div className="accounts-inline-feedback-cell">
                      {createError ? (
                        <p className="error" role="alert">
                          {createError}
                        </p>
                      ) : null}
                    </div>
                  </td>
                </tr>
              </Fragment>
            )}
            {displayAccounts.length === 0 && !isCreating && (
              <tr>
                <td colSpan={4}>
                  <p className="muted" role="status">
                    No accounts match these filters.
                  </p>
                </td>
              </tr>
            )}
            {displayAccounts.map((account) => {
              const rowId = rowIdOf(account);
              const rowActionsLocked = accountRowBusyId !== null && accountRowBusyId === rowId;
              const isEditing = editingId !== null && editingId === rowId;

              if (isEditing) {
                return (
                  <Fragment key={account.id}>
                    <tr>
                      <td>
                        <form
                          ref={editFormRef}
                          id={EDIT_FORM_ID}
                          aria-label={`Edit account ${account.name}`}
                          onSubmit={(e) => void handleEditSubmit(e, account)}
                          hidden
                        />
                        <input
                          form={EDIT_FORM_ID}
                          aria-label={`Edit name for account ${account.id}`}
                          value={draftName}
                          onChange={(e) => setDraftName(e.target.value)}
                        />
                      </td>
                      <td>
                        <select
                          form={EDIT_FORM_ID}
                          aria-label={`Edit type for account ${account.id}`}
                          value={draftType}
                          onChange={(e) => setDraftType(e.target.value as AccountType)}
                        >
                          {ACCOUNT_TYPES.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>{renderDraftActiveCell(draftActive, setDraftActive, editSubmitting, draftName.trim() || account.name)}</td>
                      <td className="table-row-actions-cell">
                        <div className="form-actions-inline">
                          <TableRowIconButton
                            type="submit"
                            form={EDIT_FORM_ID}
                            aria-label={isMac ? "Save changes (⌘+S)" : "Save changes (Ctrl+S)"}
                            title={saveActionTooltip(isMac)}
                            aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
                            disabled={editSubmitting}
                          >
                            <Save size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                          <TableRowIconButton
                            type="button"
                            className="button-secondary"
                            aria-label={discardActionTooltip(isMac)}
                            title={discardActionTooltip(isMac)}
                            aria-keyshortcuts={discardAriaKeyShortcuts(isMac)}
                            disabled={editSubmitting}
                            onClick={() => {
                              if (performance.now() < suppressRevertUntilRef.current) {
                                return;
                              }
                              revertEdit(account);
                            }}
                          >
                            <Undo2 size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                        </div>
                      </td>
                    </tr>
                    <tr
                      className={
                        editError
                          ? "accounts-inline-feedback-row"
                          : "accounts-inline-feedback-row accounts-inline-feedback-row--empty"
                      }
                      aria-hidden={!editError}
                    >
                      <td colSpan={4}>
                        <div className="accounts-inline-feedback-cell">
                          {editError ? (
                            <p className="error" role="alert">
                              {editError}
                            </p>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  </Fragment>
                );
              }

              return (
                <tr key={account.id}>
                  <td>{account.name}</td>
                  <td>{account.type}</td>
                  <td>{account.is_active ? "active" : "inactive"}</td>
                  <td className="table-row-actions-cell">
                    <div
                      className="table-row-actions"
                      role="group"
                      aria-label={`Actions for account ${account.name}`}
                    >
                      <TableRowIconButton
                        aria-label={`Edit account ${account.name}`}
                        title={`Edit account ${account.name}`}
                        disabled={rowActionsLocked}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (rowActionsLocked) {
                            return;
                          }
                          const row = account;
                          suppressRevertUntilRef.current = performance.now() + 150;
                          window.setTimeout(() => {
                            startEdit(row);
                          }, 0);
                        }}
                      >
                        <Pencil size={18} strokeWidth={2} aria-hidden />
                      </TableRowIconButton>
                      {account.is_active ? (
                        <TableRowIconButton
                          aria-label={`Deactivate account ${account.name}`}
                          title={`Deactivate account ${account.name}`}
                          disabled={rowActionsLocked}
                          onClick={() => tryDeactivateAccount(account)}
                        >
                          <SquareX size={18} strokeWidth={2} aria-hidden />
                        </TableRowIconButton>
                      ) : (
                        <TableRowIconButton
                          aria-label={`Reactivate account ${account.name}`}
                          title={`Reactivate account ${account.name}`}
                          disabled={rowActionsLocked}
                          onClick={() => tryReactivateAccount(account)}
                        >
                          <SquareCheckBig size={18} strokeWidth={2} aria-hidden />
                        </TableRowIconButton>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
