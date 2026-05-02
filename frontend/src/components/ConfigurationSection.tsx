import { FormEvent, useEffect, useState } from "react";

import type { Account } from "../api/accounts";
import { getLedgerSettings, updateLedgerSettings } from "../api/settlements";

interface ConfigurationSectionProps {
  accounts: Account[];
}

export function ConfigurationSection({ accounts }: ConfigurationSectionProps) {
  const [arId, setArId] = useState("");
  const [apId, setApId] = useState("");
  const [urId, setUrId] = useState("");
  const [unallocDrId, setUnallocDrId] = useState("");
  const [unallocCrId, setUnallocCrId] = useState("");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    async function loadSettings() {
      try {
        const settings = await getLedgerSettings();
        setArId(settings.accounts_receivable_account_id ? String(settings.accounts_receivable_account_id) : "");
        setApId(settings.accounts_payable_account_id ? String(settings.accounts_payable_account_id) : "");
        setUrId(settings.unearned_revenue_account_id ? String(settings.unearned_revenue_account_id) : "");
        setUnallocDrId(
          settings.unallocated_debits_account_id ? String(settings.unallocated_debits_account_id) : "",
        );
        setUnallocCrId(
          settings.unallocated_credits_account_id ? String(settings.unallocated_credits_account_id) : "",
        );
      } catch (err) {
        setSettingsError(err instanceof Error ? err.message : "Failed to load ledger settings");
      }
    }
    void loadSettings();
  }, []);

  async function handleSaveSettings(event: FormEvent) {
    event.preventDefault();
    setSettingsError(null);
    setSavedMessage(null);
    try {
      const settings = await updateLedgerSettings({
        accounts_receivable_account_id: arId ? Number(arId) : null,
        accounts_payable_account_id: apId ? Number(apId) : null,
        unearned_revenue_account_id: urId ? Number(urId) : null,
        unallocated_debits_account_id: unallocDrId ? Number(unallocDrId) : null,
        unallocated_credits_account_id: unallocCrId ? Number(unallocCrId) : null,
      });
      setArId(settings.accounts_receivable_account_id ? String(settings.accounts_receivable_account_id) : "");
      setApId(settings.accounts_payable_account_id ? String(settings.accounts_payable_account_id) : "");
      setUrId(settings.unearned_revenue_account_id ? String(settings.unearned_revenue_account_id) : "");
      setUnallocDrId(
        settings.unallocated_debits_account_id ? String(settings.unallocated_debits_account_id) : "",
      );
      setUnallocCrId(
        settings.unallocated_credits_account_id ? String(settings.unallocated_credits_account_id) : "",
      );
      setSavedMessage("Settings saved.");
    } catch (err) {
      setSettingsError(err instanceof Error ? err.message : "Failed to update settings");
    }
  }

  const suspenseAccounts = accounts.filter((a) => a.type === "suspense");

  return (
    <section className="card journal-card-wide">
      <h2>Configuration</h2>
      <p className="muted">
        Settlement workflow accounts (A/R, A/P, unearned revenue) and CSV import suspense buckets. Unallocated
        accounts must use the <strong>suspense</strong> type; configure those on the Accounts tab first.
      </p>
      <form onSubmit={(e) => void handleSaveSettings(e)}>
        <h3 className="config-subheading">Settlement roles</h3>
        <label>
          Accounts receivable
          <select value={arId} onChange={(e) => setArId(e.target.value)}>
            <option value="">Select asset account</option>
            {accounts.filter((a) => a.type === "asset").map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Accounts payable
          <select value={apId} onChange={(e) => setApId(e.target.value)}>
            <option value="">Select liability account</option>
            {accounts.filter((a) => a.type === "liability").map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Unearned revenue
          <select value={urId} onChange={(e) => setUrId(e.target.value)}>
            <option value="">Select liability account</option>
            {accounts.filter((a) => a.type === "liability").map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>

        <h3 className="config-subheading">CSV import — unallocated accounts</h3>
        <p className="muted">
          When a row has no debit or credit account from rules, the import posts to these suspense accounts so
          cash still balances. Without them, those rows fail validation.
        </p>
        <label>
          Unallocated debits (default debit side)
          <select value={unallocDrId} onChange={(e) => setUnallocDrId(e.target.value)}>
            <option value="">Select suspense account</option>
            {suspenseAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Unallocated credits (default credit side)
          <select value={unallocCrId} onChange={(e) => setUnallocCrId(e.target.value)}>
            <option value="">Select suspense account</option>
            {suspenseAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>

        <button type="submit">Save configuration</button>
        {settingsError && (
          <p className="error" role="alert">
            {settingsError}
          </p>
        )}
        {savedMessage && (
          <p className="muted" role="status">
            {savedMessage}
          </p>
        )}
      </form>
    </section>
  );
}
