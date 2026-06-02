import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import type { Account } from "../api/accounts";
import {
  type BackupExportType,
  type RestoreMode,
  exportBackupToDisk,
  importBackup,
} from "../api/backup";
import { getLedgerSettings, LedgerSettingsValidationError, updateLedgerSettings } from "../api/settlements";
import { accountsForSettingPicker } from "../journal/accountSelect";
import {
  discardActionTooltip,
  discardAriaKeyShortcuts,
  saveActionTooltip,
  saveAriaKeyShortcuts,
} from "../lib/keyboardHints";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";

interface ConfigurationSectionProps {
  accounts: Account[];
}

export function ConfigurationSection({ accounts }: ConfigurationSectionProps) {
  const [arId, setArId] = useState("");
  const [arBaseline, setArBaseline] = useState("");
  const [apId, setApId] = useState("");
  const [apBaseline, setApBaseline] = useState("");
  const [urId, setUrId] = useState("");
  const [urBaseline, setUrBaseline] = useState("");
  const [prepaidId, setPrepaidId] = useState("");
  const [prepaidBaseline, setPrepaidBaseline] = useState("");
  const [unallocDrId, setUnallocDrId] = useState("");
  const [unallocDrBaseline, setUnallocDrBaseline] = useState("");
  const [unallocCrId, setUnallocCrId] = useState("");
  const [unallocCrBaseline, setUnallocCrBaseline] = useState("");
  const [settingsErrors, setSettingsErrors] = useState<string[]>([]);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupMessage, setBackupMessage] = useState<string | null>(null);
  const [backupFormatWarning, setBackupFormatWarning] = useState<string | null>(null);
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupExportType, setBackupExportType] = useState<BackupExportType>("complete");
  const [restoreMode, setRestoreMode] = useState<RestoreMode>("abort");
  const restoreInputRef = useRef<HTMLInputElement>(null);
  const settingsFormRef = useRef<HTMLFormElement>(null);
  const isMac = useMemo(() => isMacLikeUserAgent(), []);

  function revertSettings() {
    setArId(arBaseline);
    setApId(apBaseline);
    setUrId(urBaseline);
    setPrepaidId(prepaidBaseline);
    setUnallocDrId(unallocDrBaseline);
    setUnallocCrId(unallocCrBaseline);
    setSettingsErrors([]);
    setSavedMessage(null);
  }

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const saveChord =
        (e.key === "s" || e.key === "S") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
      const revertChord =
        (e.key === "d" || e.key === "D") && (e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey;
      if (saveChord) {
        e.preventDefault();
        settingsFormRef.current?.requestSubmit();
        return;
      }
      if (revertChord) {
        e.preventDefault();
        revertSettings();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [arBaseline, apBaseline, urBaseline, prepaidBaseline, unallocDrBaseline, unallocCrBaseline]);

  useEffect(() => {
    async function loadSettings() {
      try {
        const settings = await getLedgerSettings();
        const ar = settings.accounts_receivable_account_id ? String(settings.accounts_receivable_account_id) : "";
        const ap = settings.accounts_payable_account_id ? String(settings.accounts_payable_account_id) : "";
        const ur = settings.unearned_revenue_account_id ? String(settings.unearned_revenue_account_id) : "";
        const prepaid = settings.prepaid_expenses_account_id
          ? String(settings.prepaid_expenses_account_id)
          : "";
        const udr = settings.unallocated_debits_account_id
          ? String(settings.unallocated_debits_account_id)
          : "";
        const ucr = settings.unallocated_credits_account_id
          ? String(settings.unallocated_credits_account_id)
          : "";
        setArId(ar);
        setArBaseline(ar);
        setApId(ap);
        setApBaseline(ap);
        setUrId(ur);
        setUrBaseline(ur);
        setPrepaidId(prepaid);
        setPrepaidBaseline(prepaid);
        setUnallocDrId(udr);
        setUnallocDrBaseline(udr);
        setUnallocCrId(ucr);
        setUnallocCrBaseline(ucr);
      } catch (err) {
        setSettingsErrors([
          err instanceof Error ? err.message : "Failed to load ledger settings",
        ]);
      }
    }
    void loadSettings();
  }, []);

  async function handleSaveSettings(event: FormEvent) {
    event.preventDefault();
    setSettingsErrors([]);
    setSavedMessage(null);
    try {
      const settings = await updateLedgerSettings({
        accounts_receivable_account_id: arId ? Number(arId) : null,
        accounts_payable_account_id: apId ? Number(apId) : null,
        unearned_revenue_account_id: urId ? Number(urId) : null,
        prepaid_expenses_account_id: prepaidId ? Number(prepaidId) : null,
        unallocated_debits_account_id: unallocDrId ? Number(unallocDrId) : null,
        unallocated_credits_account_id: unallocCrId ? Number(unallocCrId) : null,
      });
      const ar = settings.accounts_receivable_account_id ? String(settings.accounts_receivable_account_id) : "";
      const ap = settings.accounts_payable_account_id ? String(settings.accounts_payable_account_id) : "";
      const ur = settings.unearned_revenue_account_id ? String(settings.unearned_revenue_account_id) : "";
      const prepaid = settings.prepaid_expenses_account_id
        ? String(settings.prepaid_expenses_account_id)
        : "";
      const udr = settings.unallocated_debits_account_id
        ? String(settings.unallocated_debits_account_id)
        : "";
      const ucr = settings.unallocated_credits_account_id
        ? String(settings.unallocated_credits_account_id)
        : "";
      setArId(ar);
      setArBaseline(ar);
      setApId(ap);
      setApBaseline(ap);
      setUrId(ur);
      setUrBaseline(ur);
      setPrepaidId(prepaid);
      setPrepaidBaseline(prepaid);
      setUnallocDrId(udr);
      setUnallocDrBaseline(udr);
      setUnallocCrId(ucr);
      setUnallocCrBaseline(ucr);
      setSavedMessage("Settings saved.");
    } catch (err) {
      if (err instanceof LedgerSettingsValidationError) {
        setSettingsErrors(err.errors);
        return;
      }
      setSettingsErrors([
        err instanceof Error ? err.message : "Failed to update settings",
      ]);
    }
  }

  const assetAccounts = accounts.filter((a) => a.type === "asset");
  const liabilityAccounts = accounts.filter((a) => a.type === "liability");
  const suspenseAccounts = accounts.filter((a) => a.type === "suspense");

  return (
    <section className="card journal-card-wide">
      <h2>Configuration</h2>
      <p className="muted">
        Settlement workflow accounts (A/R, A/P, unearned revenue, prepaid expenses) and CSV import suspense
        buckets. Unallocated
        accounts must use the <strong>suspense</strong> type; configure those on the Accounts tab first.
      </p>
      <form ref={settingsFormRef} onSubmit={(e) => void handleSaveSettings(e)}>
        <h3 className="config-subheading">Settlement roles</h3>
        <label>
          Accounts receivable
          <select value={arId} onChange={(e) => setArId(e.target.value)}>
            <option value="">Select asset account</option>
            {accountsForSettingPicker(assetAccounts, arId, arBaseline).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {!a.is_active ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Accounts payable
          <select value={apId} onChange={(e) => setApId(e.target.value)}>
            <option value="">Select liability account</option>
            {accountsForSettingPicker(liabilityAccounts, apId, apBaseline).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {!a.is_active ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Unearned revenue
          <select value={urId} onChange={(e) => setUrId(e.target.value)}>
            <option value="">Select liability account</option>
            {accountsForSettingPicker(liabilityAccounts, urId, urBaseline).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {!a.is_active ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Prepaid expenses
          <select value={prepaidId} onChange={(e) => setPrepaidId(e.target.value)}>
            <option value="">Select asset account</option>
            {accountsForSettingPicker(assetAccounts, prepaidId, prepaidBaseline).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {!a.is_active ? " (inactive)" : ""}
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
            {accountsForSettingPicker(suspenseAccounts, unallocDrId, unallocDrBaseline).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {!a.is_active ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Unallocated credits (default credit side)
          <select value={unallocCrId} onChange={(e) => setUnallocCrId(e.target.value)}>
            <option value="">Select suspense account</option>
            {accountsForSettingPicker(suspenseAccounts, unallocCrId, unallocCrBaseline).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {!a.is_active ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </label>

        <div className="form-actions-inline">
          <button
            type="submit"
            title={saveActionTooltip(isMac)}
            aria-label={isMac ? "Save configuration (⌘+S)" : "Save configuration (Ctrl+S)"}
            aria-keyshortcuts={saveAriaKeyShortcuts(isMac)}
          >
            Save configuration
          </button>
          <button
            type="button"
            className="button-secondary"
            onClick={revertSettings}
            title={discardActionTooltip(isMac)}
            aria-label={discardActionTooltip(isMac)}
            aria-keyshortcuts={discardAriaKeyShortcuts(isMac)}
          >
            Discard
          </button>
        </div>
        {settingsErrors.map((message, index) => (
          <p key={`settings-error-${index}`} className="error-text" role="alert">
            {message}
          </p>
        ))}
        {savedMessage && (
          <p className="muted" role="status">
            {savedMessage}
          </p>
        )}
      </form>

      <h3 className="config-subheading">Backup &amp; restore</h3>
      <p className="muted">
        Exports a versioned <strong>tar.gz</strong> of JSON table dumps (legacy <strong>.zip</strong> still
        accepted on import). Format:{" "}
        <a href="https://github.com/brettski74/TallyBadger/blob/main/docs/backup-snapshot-format.md">
          docs/backup-snapshot-format.md
        </a>
        . The archive records <strong>what</strong> was exported; restore behaviour is chosen below on each
        import.
      </p>
      <p className="muted">
        Large databases can produce a big archive—the request may take a while with no progress bar; wait until
        the download finishes or the server returns an error. Supported browsers stream the export directly to
        disk; others fall back to a conventional download.
      </p>
      <label className="backup-export-scope">
        Export scope
        <select
          value={backupExportType}
          onChange={(e) => setBackupExportType(e.target.value as BackupExportType)}
          disabled={backupBusy}
        >
          <option value="complete">Complete — configuration + financial data</option>
          <option value="configuration">Configuration — chart, parties, templates, settings (no ledger or accrual plans)</option>
          <option value="financial">Financial — ledger, accrual plans, obligations, settlements</option>
        </select>
      </label>

      <h3 className="config-subheading">Restore from backup</h3>
      <p className="muted">
        <strong>Duplicate / conflict policy</strong> (this request only): how to merge when the database
        already has rows that collide with the snapshot (same primary keys or unique keys).{" "}
        <strong>Financial-only</strong> archives need matching configuration already in the database, unless
        you use erase+reload after importing a <strong>complete</strong> or <strong>configuration</strong>{" "}
        snapshot first.
      </p>
      <label className="backup-import-policy">
        On duplicate keys (restore mode)
        <select
          value={restoreMode}
          onChange={(e) => setRestoreMode(e.target.value as RestoreMode)}
          disabled={backupBusy}
        >
          <option value="abort">Abort — stop on first conflict (default)</option>
          <option value="overwrite">Overwrite — delete snapshot IDs in the DB, then insert</option>
          <option value="erase-reload">Erase + reload — truncate all app data tables, then load</option>
        </select>
      </label>
      <div className="backup-actions">
        <button
          type="button"
          disabled={backupBusy}
          onClick={() => {
            void (async () => {
              setBackupError(null);
              setBackupMessage(null);
              setBackupFormatWarning(null);
              setBackupBusy(true);
              try {
                await exportBackupToDisk(backupExportType);
                setBackupMessage("Backup file saved.");
              } catch (err) {
                setBackupError(err instanceof Error ? err.message : "Export failed");
              } finally {
                setBackupBusy(false);
              }
            })();
          }}
        >
          Download backup
        </button>
        <input
          ref={restoreInputRef}
          type="file"
          accept=".zip,.tar.gz,.tgz,application/zip,application/gzip"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            void (async () => {
              setBackupError(null);
              setBackupMessage(null);
              setBackupFormatWarning(null);
              setBackupBusy(true);
              try {
                const result = await importBackup(file, restoreMode);
                setBackupMessage("Restore finished successfully.");
                if (result.formatDeprecationWarning) {
                  setBackupFormatWarning(result.formatDeprecationWarning);
                }
              } catch (err) {
                setBackupError(err instanceof Error ? err.message : "Restore failed");
              } finally {
                setBackupBusy(false);
              }
            })();
          }}
        />
        <button
          type="button"
          disabled={backupBusy}
          onClick={() => {
            restoreInputRef.current?.click();
          }}
        >
          Restore from backup…
        </button>
      </div>
      {backupError && (
        <p className="error" role="alert">
          {backupError}
        </p>
      )}
      {backupMessage && (
        <p className="muted" role="status">
          {backupMessage}
        </p>
      )}
      {backupFormatWarning && (
        <p className="error-text" role="alert">
          {backupFormatWarning}
        </p>
      )}
    </section>
  );
}
