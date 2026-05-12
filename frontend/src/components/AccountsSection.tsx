import type { CSSProperties } from "react";
import { FormEvent, useMemo, useRef, useState } from "react";
import { Pencil, Save, SquareCheckBig, SquareX, Undo2 } from "lucide-react";

import {
  Account,
  AccountType,
  createAccount,
  updateAccount,
  UpdateAccountInput,
} from "../api/accounts";
import { useFormSaveDiscardShortcuts } from "../hooks/useFormSaveDiscardShortcuts";
import {
  discardActionTooltip,
  discardAriaKeyShortcuts,
  saveActionTooltip,
  saveAriaKeyShortcuts,
} from "../lib/keyboardHints";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";
import { TableRowIconButton } from "./TableRowIconButton";

const ACCOUNT_TYPES: AccountType[] = ["asset", "liability", "equity", "revenue", "expense", "suspense"];

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

  const isMac = useMemo(() => isMacLikeUserAgent(), []);

  function discardInlineCreate() {
    setIsCreating(false);
    setCreateDraftName("");
    setCreateDraftType("asset");
    setCreateDraftActive(true);
    setCreateError(null);
    setCreateSubmitting(false);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError(null);
  }

  function startCreate() {
    if (isCreating) {
      discardInlineCreate();
    }
    if (editingId !== null) {
      cancelEdit();
    }
    setIsCreating(true);
    setCreateDraftName("");
    setCreateDraftType("asset");
    setCreateDraftActive(true);
    setCreateError(null);
    setRowActionError(null);
  }

  function startEdit(account: Account) {
    if (isCreating) {
      discardInlineCreate();
    }
    if (editingId !== null && editingId !== account.id) {
      cancelEdit();
    }
    setEditingId(account.id);
    setDraftName(account.name);
    setDraftType(account.type);
    setDraftActive(account.is_active);
    setEditError(null);
    setRowActionError(null);
  }

  useFormSaveDiscardShortcuts({
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
    requestEditDiscard: () => {
      cancelEdit();
    },
    requestCreateDiscard: () => {
      discardInlineCreate();
    },
  });

  async function patchAccountActive(account: Account, nextActive: boolean) {
    setRowActionError(null);
    setAccountRowBusyId(account.id);
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
      discardInlineCreate();
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
      cancelEdit();
      return;
    }

    setEditSubmitting(true);
    try {
      const updated = await updateAccount(original.id, body);
      onAccountUpdated(updated);
      cancelEdit();
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
      <div className="card-heading-row">
        <h2>Accounts</h2>
        <button type="button" onClick={startCreate}>
          Create account
        </button>
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
              <th aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {isCreating && (
              <tr key="__inline-create__">
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
                <td>
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
                      onClick={discardInlineCreate}
                    >
                      <Undo2 size={18} strokeWidth={2} aria-hidden />
                    </TableRowIconButton>
                  </div>
                  {createError && (
                    <p className="error" role="alert">
                      {createError}
                    </p>
                  )}
                </td>
              </tr>
            )}
            {accounts.map((account) => {
              const rowActionsLocked = accountRowBusyId !== null;
              const isEditing = editingId === account.id;

              if (isEditing) {
                return (
                  <tr key={account.id}>
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
                    <td>
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
                          onClick={cancelEdit}
                        >
                          <Undo2 size={18} strokeWidth={2} aria-hidden />
                        </TableRowIconButton>
                      </div>
                      {editError && (
                        <p className="error" role="alert">
                          {editError}
                        </p>
                      )}
                    </td>
                  </tr>
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
                        onClick={() => startEdit(account)}
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
