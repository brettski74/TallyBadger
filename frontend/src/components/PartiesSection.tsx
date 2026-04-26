import { FormEvent, useState } from "react";

import {
  createParty,
  updateParty,
  type Party,
  type PartyCreateInput,
  type PartyRole,
} from "../api/parties";

const PARTY_ROLES: PartyRole[] = ["customer", "vendor", "both", "other"];

interface PartiesSectionProps {
  parties: Party[];
  loading: boolean;
  error: string | null;
  onPartyCreated: (party: Party) => void;
  onPartyUpdated: (party: Party) => void;
}

export function PartiesSection({ parties, loading, error, onPartyCreated, onPartyUpdated }: PartiesSectionProps) {
  const [createError, setCreateError] = useState<string | null>(null);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState<PartyRole>("both");
  const [isActive, setIsActive] = useState(true);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState<PartyRole>("both");
  const [editActive, setEditActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);

  function startEdit(party: Party) {
    setEditingId(party.id);
    setEditName(party.name);
    setEditRole(party.role);
    setEditActive(party.is_active);
    setEditError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError(null);
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
      const payload: PartyCreateInput = { name: name.trim(), role, is_active: isActive };
      const created = await createParty(payload);
      onPartyCreated(created);
      setName("");
      setRole("both");
      setIsActive(true);
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
      const updated = await updateParty(editingId, {
        name: editName.trim(),
        role: editRole,
        is_active: editActive,
      });
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
                <th>Status</th>
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {parties.map((party) => (
                <tr key={party.id}>
                  <td>{party.name}</td>
                  <td>{party.role}</td>
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
