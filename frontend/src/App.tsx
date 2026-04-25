import { useCallback, useEffect, useState } from "react";

import hugeLogo from "./assets/branding/TallyBadgerHuge.png";
import { Account, listAccounts } from "./api/accounts";
import { AccountsSection } from "./components/AccountsSection";
import { JournalEntriesPanel } from "./components/JournalEntriesPanel";

type MainTab = "accounts" | "journal";

function App() {
  const [tab, setTab] = useState<MainTab>("accounts");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAccounts = useCallback(async () => {
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
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  function handleAccountCreated(created: Account) {
    setAccounts((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <img src={hugeLogo} alt="TallyBadger logo" className="logo" />
        <div>
          <h1>TallyBadger</h1>
          <p>Ledger: chart of accounts and journal entries</p>
        </div>
      </header>

      <nav className="app-nav" aria-label="Main">
        <button
          type="button"
          className={tab === "accounts" ? "app-nav-active" : undefined}
          onClick={() => setTab("accounts")}
        >
          Accounts
        </button>
        <button
          type="button"
          className={tab === "journal" ? "app-nav-active" : undefined}
          onClick={() => setTab("journal")}
        >
          Journal entries
        </button>
      </nav>

      <main className="content">
        {tab === "accounts" && (
          <AccountsSection
            accounts={accounts}
            loading={loading}
            error={error}
            onAccountCreated={handleAccountCreated}
          />
        )}
        {tab === "journal" && (
          <JournalEntriesPanel accounts={accounts} accountsLoading={loading} accountsError={error} />
        )}
      </main>
    </div>
  );
}

export default App;
