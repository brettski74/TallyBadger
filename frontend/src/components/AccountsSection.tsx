import { FormEvent, useState } from "react";

import { Account, AccountType, createAccount, updateAccount, UpdateAccountInput } from "../api/accounts";

const ACCOUNT_TYPES: AccountType[] = ["asset", "liability", "equity", "revenue", "expense", "suspense"];

const RENAME_CEL_WARNING =
  "Renaming an account can break CEL rules, import templates, or other text that matched the old name. " +
  "Only continue if you have checked those references (or enjoy surprise import failures — we don't judge, much). Continue anyway?";

const TYPE_CHANGE_CONFIRM =
  "Changing an account's type is unusual — reports and rules may have filed this under the old label. " +
  "Continue only if the original pick was genuinely wrong. Proceed anyway?";

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
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("asset");
  const [isActive, setIsActive] = useState(true);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftType, setDraftType] = useState<AccountType>("asset");
  const [draftActive, setDraftActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    if (!name.trim()) {
      setSubmitError("Account name is required");
      return;
    }
    setSubmitting(true);
    try {
      const created = await createAccount({ name: name.trim(), type, is_active: isActive });
      onAccountCreated(created);
      setName("");
      setType("asset");
      setIsActive(true);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create account");
    } finally {
      setSubmitting(false);
    }
  }

  function startEdit(account: Account) {
    setEditingId(account.id);
    setDraftName(account.name);
    setDraftType(account.type);
    setDraftActive(account.is_active);
    setEditError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError(null);
  }

  async function saveEdit(original: Account) {
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
      setEditingId(null);
      return;
    }

    setEditSubmitting(true);
    try {
      const updated = await updateAccount(original.id, body);
      onAccountUpdated(updated);
      setEditingId(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update account");
    } finally {
      setEditSubmitting(false);
    }
  }

  return (
    <>
      <section className="card">
        <h2>Create account</h2>
        <form onSubmit={(e) => void handleSubmit(e)}>
          <label>
            Name
            <input
              aria-label="Account name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Cash"
            />
          </label>

          <label>
            Type
            <select
              aria-label="Account type"
              value={type}
              onChange={(event) => setType(event.target.value as AccountType)}
            >
              {ACCOUNT_TYPES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label className="checkbox">
            <input
              aria-label="Account active"
              type="checkbox"
              checked={isActive}
              onChange={(event) => setIsActive(event.target.checked)}
            />
            Active account
          </label>

          <button disabled={submitting} type="submit">
            {submitting ? "Creating..." : "Create account"}
          </button>

          {submitError && (
            <p className="error" role="alert">
              {submitError}
            </p>
          )}
        </form>
      </section>

      <section className="card">
        <h2>Accounts</h2>

        {loading && <p>Loading accounts...</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!loading && !error && accounts.length === 0 && <p>No accounts yet.</p>}

        {!loading && !error && accounts.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => (
                <tr key={account.id}>
                  {editingId === account.id ? (
                    <>
                      <td>
                        <input
                          aria-label={`Edit name for account ${account.id}`}
                          value={draftName}
                          onChange={(event) => setDraftName(event.target.value)}
                        />
                      </td>
                      <td>
                        <select
                          aria-label={`Edit type for account ${account.id}`}
                          value={draftType}
                          onChange={(event) => setDraftType(event.target.value as AccountType)}
                        >
                          {ACCOUNT_TYPES.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <label className="checkbox">
                          <input
                            aria-label={`Edit active for account ${account.id}`}
                            type="checkbox"
                            checked={draftActive}
                            onChange={(event) => setDraftActive(event.target.checked)}
                          />
                          Active
                        </label>
                      </td>
                      <td>
                        <button
                          type="button"
                          disabled={editSubmitting}
                          onClick={() => void saveEdit(account)}
                        >
                          {editSubmitting ? "Saving…" : "Save"}
                        </button>{" "}
                        <button type="button" disabled={editSubmitting} onClick={cancelEdit}>
                          Cancel
                        </button>
                        {editError && (
                          <p className="error" role="alert">
                            {editError}
                          </p>
                        )}
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{account.name}</td>
                      <td>{account.type}</td>
                      <td>{account.is_active ? "active" : "inactive"}</td>
                      <td>
                        <button type="button" onClick={() => startEdit(account)}>
                          Edit
                        </button>
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
