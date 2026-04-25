import { FormEvent, useEffect, useState } from "react";

import hugeLogo from "./assets/branding/TallyBadgerHuge.png";
import { Account, AccountType, createAccount, listAccounts } from "./api/accounts";

const ACCOUNT_TYPES: AccountType[] = ["asset", "liability", "equity", "revenue", "expense"];

function App() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("asset");
  const [isActive, setIsActive] = useState(true);

  async function loadAccounts() {
    setLoading(true);
    setError(null);
    try {
      const data = await listAccounts();
      setAccounts(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load accounts");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAccounts();
  }, []);

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
      setAccounts((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      setName("");
      setType("asset");
      setIsActive(true);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create account");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <img src={hugeLogo} alt="TallyBadger logo" className="logo" />
        <div>
          <h1>TallyBadger</h1>
          <p>Phase 2 foundation: chart of accounts management</p>
        </div>
      </header>

      <main className="content">
        <section className="card">
          <h2>Create account</h2>
          <form onSubmit={handleSubmit}>
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
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <tr key={account.id}>
                    <td>{account.name}</td>
                    <td>{account.type}</td>
                    <td>{account.is_active ? "active" : "inactive"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;
