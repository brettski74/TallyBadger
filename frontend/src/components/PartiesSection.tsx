import { FormEvent, useEffect, useMemo, useState } from "react";

import type { Account } from "../api/accounts";
import {
  createParty,
  listPartySubtypeSuggestions,
  updateParty,
  type Party,
  type PartyCreateInput,
  type PartyRole,
} from "../api/parties";

const PARTY_ROLES: PartyRole[] = ["customer", "vendor", "both", "other"];

const DOCS_CEL_HINT =
  "Regex patterns are used by import CEL rules (party() function). See docs/cel-function-reference.md in the repo.";

interface PartiesSectionProps {
  parties: Party[];
  accounts: Account[];
  loading: boolean;
  error: string | null;
  onPartyCreated: (party: Party) => void;
  onPartyUpdated: (party: Party) => void;
}

function revenuePickable(role: PartyRole): boolean {
  return role === "customer" || role === "both";
}

function expensePickable(role: PartyRole): boolean {
  return role === "vendor" || role === "both";
}

export function PartiesSection({
  parties,
  accounts,
  loading,
  error,
  onPartyCreated,
  onPartyUpdated,
}: PartiesSectionProps) {
  const [subtypeSuggestions, setSubtypeSuggestions] = useState<string[]>([]);

  const [createError, setCreateError] = useState<string | null>(null);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState<PartyRole>("both");
  const [isActive, setIsActive] = useState(true);
  const [subtype, setSubtype] = useState("");
  const [createPatterns, setCreatePatterns] = useState<string[]>([""]);
  const [createDefRev, setCreateDefRev] = useState("");
  const [createDefExp, setCreateDefExp] = useState("");

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState<PartyRole>("both");
  const [editActive, setEditActive] = useState(true);
  const [editSubtype, setEditSubtype] = useState("");
  const [editPatterns, setEditPatterns] = useState<string[]>([""]);
  const [editDefRev, setEditDefRev] = useState("");
  const [editDefExp, setEditDefExp] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);

  const revenueAccounts = useMemo(
    () => accounts.filter((a) => a.type === "revenue" && a.is_active).sort((a, b) => a.name.localeCompare(b.name)),
    [accounts],
  );
  const expenseAccounts = useMemo(
    () => accounts.filter((a) => a.type === "expense" && a.is_active).sort((a, b) => a.name.localeCompare(b.name)),
    [accounts],
  );

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
  }, [parties]);

  function startEdit(party: Party) {
    setEditingId(party.id);
    setEditName(party.name);
    setEditRole(party.role);
    setEditActive(party.is_active);
    setEditSubtype(party.subtype ?? "");
    const pats = party.match_patterns?.length ? [...party.match_patterns] : [""];
    setEditPatterns(pats);
    setEditDefRev(party.default_revenue_account_id != null ? String(party.default_revenue_account_id) : "");
    setEditDefExp(party.default_expense_account_id != null ? String(party.default_expense_account_id) : "");
    setEditError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError(null);
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
      setCreatePatterns((prev) => [...prev, ""]);
    } else {
      setEditPatterns((prev) => [...prev, ""]);
    }
  }

  function removePatternRow(which: "create" | "edit", index: number) {
    if (which === "create") {
      setCreatePatterns((prev) => (prev.length <= 1 ? [""] : prev.filter((_, i) => i !== index)));
    } else {
      setEditPatterns((prev) => (prev.length <= 1 ? [""] : prev.filter((_, i) => i !== index)));
    }
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
      const patterns = createPatterns.map((p) => p.trim()).filter(Boolean);
      const payload: PartyCreateInput = {
        name: name.trim(),
        role,
        is_active: isActive,
        match_patterns: patterns,
      };
      if (subtype.trim()) {
        payload.subtype = subtype.trim();
      }
      if (revenuePickable(role) && createDefRev) {
        payload.default_revenue_account_id = Number(createDefRev);
      }
      if (expensePickable(role) && createDefExp) {
        payload.default_expense_account_id = Number(createDefExp);
      }
      const created = await createParty(payload);
      onPartyCreated(created);
      setName("");
      setRole("both");
      setIsActive(true);
      setSubtype("");
      setCreatePatterns([""]);
      setCreateDefRev("");
      setCreateDefExp("");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create party");
    } finally {
      setCreateSubmitting(false);
    }
  }

  async function handleEditSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editingId == null) {
      return;
    }
    setEditError(null);
    if (!editName.trim()) {
      setEditError("Party name is required");
      return;
    }
    setEditSubmitting(true);
    try {
      const patterns = editPatterns.map((p) => p.trim()).filter(Boolean);
      const patch = {
        name: editName.trim(),
        role: editRole,
        is_active: editActive,
        match_patterns: patterns,
        subtype: editSubtype.trim() ? editSubtype.trim() : null,
        default_revenue_account_id: null as number | null,
        default_expense_account_id: null as number | null,
      };
      if (revenuePickable(editRole)) {
        patch.default_revenue_account_id = editDefRev ? Number(editDefRev) : null;
      }
      if (expensePickable(editRole)) {
        patch.default_expense_account_id = editDefExp ? Number(editDefExp) : null;
      }
      const updated = await updateParty(editingId, patch);
      onPartyUpdated(updated);
      cancelEdit();
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update party");
    } finally {
      setEditSubmitting(false);
    }
  }

  return (
    <>
      <section className="card">
        <h2>Create party</h2>
        <p className="muted">
          Tenants, vendors, or both (e.g. a tenant who also invoices you). Parties can be linked on journal lines.
        </p>
        <form onSubmit={(e) => void handleCreate(e)}>
          <label>
            Name
            <input
              aria-label="Party name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Acme Yard Maintenance"
            />
          </label>

          <label>
            Role
            <select
              aria-label="Party role"
              value={role}
              onChange={(e) => setRole(e.target.value as PartyRole)}
            >
              {PARTY_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>

          <label>
            Subtype (optional)
            <input
              aria-label="Party subtype"
              value={subtype}
              onChange={(e) => setSubtype(e.target.value)}
              placeholder="e.g. Tenant, Utilities"
              list="party-subtype-suggestions"
            />
            <datalist id="party-subtype-suggestions">
              {subtypeSuggestions.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </label>

          <fieldset>
            <legend>Match patterns (optional)</legend>
            <p className="muted" style={{ marginTop: 0 }}>
              {DOCS_CEL_HINT}
            </p>
            {createPatterns.map((pat, index) => (
              <div key={`cp-${index}`} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
                <label style={{ flex: 1 }}>
                  Pattern {index + 1}
                  <input
                    aria-label={`Create match pattern ${index + 1}`}
                    value={pat}
                    onChange={(e) => setPatternAt("create", index, e.target.value)}
                    placeholder="Python re.search regex"
                  />
                </label>
                <button type="button" className="button-secondary" onClick={() => removePatternRow("create", index)}>
                  Remove
                </button>
              </div>
            ))}
            <button type="button" className="button-secondary" onClick={() => addPatternRow("create")}>
              Add pattern
            </button>
          </fieldset>

          {revenuePickable(role) && (
            <label>
              Default revenue account (optional)
              <select
                aria-label="Default revenue account"
                value={createDefRev}
                onChange={(e) => setCreateDefRev(e.target.value)}
              >
                <option value="">— none —</option>
                {revenueAccounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {expensePickable(role) && (
            <label>
              Default expense account (optional)
              <select
                aria-label="Default expense account"
                value={createDefExp}
                onChange={(e) => setCreateDefExp(e.target.value)}
              >
                <option value="">— none —</option>
                {expenseAccounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="checkbox">
            <input
              aria-label="Party active"
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            Active
          </label>

          <button disabled={createSubmitting} type="submit">
            {createSubmitting ? "Creating..." : "Create party"}
          </button>

          {createError && (
            <p className="error" role="alert">
              {createError}
            </p>
          )}
        </form>
      </section>

      {editingId != null && (
        <section className="card">
          <h2>Edit party</h2>
          <form onSubmit={(e) => void handleEditSave(e)}>
            <label>
              Name
              <input
                aria-label="Edit party name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
              />
            </label>

            <label>
              Role
              <select
                aria-label="Edit party role"
                value={editRole}
                onChange={(e) => setEditRole(e.target.value as PartyRole)}
              >
                {PARTY_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Subtype (optional)
              <input
                aria-label="Edit party subtype"
                value={editSubtype}
                onChange={(e) => setEditSubtype(e.target.value)}
                list="party-subtype-suggestions-edit"
              />
              <datalist id="party-subtype-suggestions-edit">
                {subtypeSuggestions.map((s) => (
                  <option key={`e-${s}`} value={s} />
                ))}
              </datalist>
            </label>

            <fieldset>
              <legend>Match patterns</legend>
              <p className="muted" style={{ marginTop: 0 }}>
                {DOCS_CEL_HINT}
              </p>
              {editPatterns.map((pat, index) => (
                <div key={`ep-${index}`} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
                  <label style={{ flex: 1 }}>
                    Pattern {index + 1}
                    <input
                      aria-label={`Edit match pattern ${index + 1}`}
                      value={pat}
                      onChange={(e) => setPatternAt("edit", index, e.target.value)}
                    />
                  </label>
                  <button type="button" className="button-secondary" onClick={() => removePatternRow("edit", index)}>
                    Remove
                  </button>
                </div>
              ))}
              <button type="button" className="button-secondary" onClick={() => addPatternRow("edit")}>
                Add pattern
              </button>
            </fieldset>

            {revenuePickable(editRole) && (
              <label>
                Default revenue account
                <select
                  aria-label="Edit default revenue account"
                  value={editDefRev}
                  onChange={(e) => setEditDefRev(e.target.value)}
                >
                  <option value="">— none —</option>
                  {revenueAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {expensePickable(editRole) && (
              <label>
                Default expense account
                <select
                  aria-label="Edit default expense account"
                  value={editDefExp}
                  onChange={(e) => setEditDefExp(e.target.value)}
                >
                  <option value="">— none —</option>
                  {expenseAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <label className="checkbox">
              <input
                aria-label="Edit party active"
                type="checkbox"
                checked={editActive}
                onChange={(e) => setEditActive(e.target.checked)}
              />
              Active
            </label>

            <div className="form-actions-inline">
              <button disabled={editSubmitting} type="submit">
                {editSubmitting ? "Saving..." : "Save changes"}
              </button>
              <button type="button" className="button-secondary" onClick={cancelEdit}>
                Cancel
              </button>
            </div>

            {editError && (
              <p className="error" role="alert">
                {editError}
              </p>
            )}
          </form>
        </section>
      )}

      <section className="card">
        <h2>Parties</h2>

        {loading && <p>Loading parties…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!loading && !error && parties.length === 0 && <p>No parties yet.</p>}

        {!loading && !error && parties.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Role</th>
                <th>Subtype</th>
                <th>Patterns</th>
                <th>Status</th>
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {parties.map((party) => (
                <tr key={party.id}>
                  <td>{party.name}</td>
                  <td>{party.role}</td>
                  <td>{party.subtype ?? "—"}</td>
                  <td>{party.match_patterns?.length ? `${party.match_patterns.length} regex` : "—"}</td>
                  <td>{party.is_active ? "active" : "inactive"}</td>
                  <td>
                    <button type="button" className="button-link" onClick={() => startEdit(party)}>
                      Edit
                    </button>
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
