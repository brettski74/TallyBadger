import { useCallback, useEffect, useState } from "react";

import headerLogo from "./assets/branding/TallyBadgerSimple-192.png";
import { Account, listAccounts } from "./api/accounts";
import { Party, listParties } from "./api/parties";
import { AccountsSection } from "./components/AccountsSection";
import { JournalEntriesPanel } from "./components/JournalEntriesPanel";
import { PartiesSection } from "./components/PartiesSection";

type MainTab = "accounts" | "journal" | "parties";

function App() {
  const [tab, setTab] = useState<MainTab>("accounts");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [accountData, partyData] = await Promise.all([listAccounts(), listParties()]);
      setAccounts(accountData);
      setParties(partyData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load accounts and parties");
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

  function handlePartyCreated(created: Party) {
    setParties((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
  }

  function handlePartyUpdated(updated: Party) {
    setParties((prev) =>
      prev.map((p) => (p.id === updated.id ? updated : p)).sort((a, b) => a.name.localeCompare(b.name)),
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-main">
          <img src={headerLogo} alt="TallyBadger" className="app-header-logo" width={192} height={192} />
          <div className="app-header-text">
            <h1>TallyBadger</h1>
            <p>Ledger: chart of accounts and journal entries</p>
          </div>
        </div>
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
          <button
            type="button"
            className={tab === "parties" ? "app-nav-active" : undefined}
            onClick={() => setTab("parties")}
          >
            Parties
          </button>
        </nav>
      </header>

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
          <JournalEntriesPanel
            accounts={accounts}
            parties={parties}
            accountsLoading={loading}
            accountsError={error}
          />
        )}
        {tab === "parties" && (
          <PartiesSection
            parties={parties}
            loading={loading}
            error={error}
            onPartyCreated={handlePartyCreated}
            onPartyUpdated={handlePartyUpdated}
          />
        )}
      </main>
    </div>
  );
}

export default App;
