import { useCallback, useEffect, useState } from "react";
import { Paperclip, Pencil } from "lucide-react";

import type { Account } from "../api/accounts";
import type { Cheque } from "../api/cheques";
import { getCheque, listCheques } from "../api/cheques";
import type { Party } from "../api/parties";
import {
  createJournalEntry,
  getJournalEntry,
  listJournalEntries,
  updateJournalEntry,
  type JournalEntryListItem,
  type JournalEntryReviewMessage,
  type JournalEntryWrite,
} from "../api/journalEntries";
import { JournalEntryAttachmentsDialog } from "./JournalEntryAttachmentsDialog";
import { JournalEntryForm, type LineDraft } from "./JournalEntryForm";
import { TableRowIconButton } from "./TableRowIconButton";

const PAGE_SIZE = 50;

function linesFromEntry(
  lines: {
    id: number;
    account_id: number;
    amount: string;
    account_name: string;
    party_id?: number | null;
    party_name?: string | null;
  }[],
): LineDraft[] {
  return lines.map((l) => ({
    key: `jl-${l.id}`,
    account_id: l.account_id,
    party_id: l.party_id ?? "",
    amount: l.amount,
    account_name: l.account_name,
    party_name: l.party_name ?? undefined,
  }));
}

interface JournalEntriesPanelProps {
  accounts: Account[];
  parties: Party[];
  accountsLoading: boolean;
  accountsError: string | null;
}

export function JournalEntriesPanel({
  accounts,
  parties,
  accountsLoading,
  accountsError,
}: JournalEntriesPanelProps) {
  const [view, setView] = useState<"list" | "form">("list");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [entries, setEntries] = useState<JournalEntryListItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);

  const [formEntryDate, setFormEntryDate] = useState("");
  const [formSummary, setFormSummary] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formReviewMessages, setFormReviewMessages] = useState<JournalEntryReviewMessage[]>([]);
  const [formLines, setFormLines] = useState<LineDraft[] | null>(null);
  const [formLoading, setFormLoading] = useState(false);
  const [formLoadError, setFormLoadError] = useState<string | null>(null);
  const [formChequeChoices, setFormChequeChoices] = useState<Cheque[]>([]);
  const [formInitialChequeId, setFormInitialChequeId] = useState<number | null>(null);
  const [attachmentsEntryId, setAttachmentsEntryId] = useState<number | null>(null);

  const refreshList = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const batch = await listJournalEntries({
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        needs_review: needsReviewOnly || undefined,
        limit: PAGE_SIZE,
        offset: 0,
      });
      setEntries(batch);
      setHasMore(batch.length === PAGE_SIZE);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load journal entries");
    } finally {
      setListLoading(false);
    }
  }, [fromDate, toDate, needsReviewOnly]);

  useEffect(() => {
    if (view !== "list") {
      return;
    }
    void refreshList();
  }, [view, refreshList]);

  async function loadMore() {
    setListLoading(true);
    setListError(null);
    try {
      const batch = await listJournalEntries({
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        needs_review: needsReviewOnly || undefined,
        limit: PAGE_SIZE,
        offset: entries.length,
      });
      setEntries((prev) => [...prev, ...batch]);
      setHasMore(batch.length === PAGE_SIZE);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load journal entries");
    } finally {
      setListLoading(false);
    }
  }

  async function openCreate() {
    setEditingId(null);
    setFormInitialChequeId(null);
    setFormEntryDate(new Date().toISOString().slice(0, 10));
    setFormSummary("");
    setFormDescription("");
    setFormReviewMessages([]);
    setFormLines(null);
    setFormLoadError(null);
    setView("form");
    setFormLoading(true);
    try {
      const open = await listCheques({ status: "open" });
      setFormChequeChoices(open);
    } catch {
      setFormChequeChoices([]);
    } finally {
      setFormLoading(false);
    }
  }

  async function openEdit(id: number) {
    setEditingId(id);
    setFormLoadError(null);
    setFormLoading(true);
    setView("form");
    try {
      const [entry, open] = await Promise.all([
        getJournalEntry(id),
        listCheques({ status: "open" }),
      ]);
      let choices = [...open];
      const cid = entry.cheque_id ?? null;
      if (cid != null) {
        const linked = await getCheque(cid);
        if (!choices.some((c) => c.id === linked.id)) {
          choices = [...choices, linked];
        }
      }
      setFormChequeChoices(choices);
      setFormInitialChequeId(cid);
      setFormEntryDate(entry.entry_date);
      setFormSummary(entry.summary);
      setFormDescription(entry.description ?? "");
      setFormReviewMessages(entry.review_messages ?? []);
      setFormLines(linesFromEntry(entry.lines));
    } catch (err) {
      setFormLoadError(err instanceof Error ? err.message : "Failed to load entry");
      setFormLines(null);
      setFormChequeChoices([]);
      setFormInitialChequeId(null);
    } finally {
      setFormLoading(false);
    }
  }

  async function handleSubmit(payload: JournalEntryWrite) {
    if (editingId == null) {
      await createJournalEntry(payload);
    } else {
      await updateJournalEntry(editingId, payload);
    }
    setView("list");
    await refreshList();
  }

  async function reloadReviewMessagesForEditor() {
    if (editingId == null) {
      return;
    }
    const entry = await getJournalEntry(editingId);
    setFormReviewMessages(entry.review_messages ?? []);
  }

  function handleCancelForm() {
    setView("list");
    setEditingId(null);
    setFormSummary("");
    setFormLines(null);
    setFormLoadError(null);
    setFormChequeChoices([]);
    setFormInitialChequeId(null);
  }

  if (accountsLoading && accounts.length === 0) {
    return (
      <section className="card journal-card-wide">
        <p>Loading chart of accounts…</p>
      </section>
    );
  }

  if (accountsError && accounts.length === 0) {
    return (
      <section className="card journal-card-wide">
        <p className="error" role="alert">
          {accountsError}
        </p>
        <p className="muted">Fix account loading to use journal lines.</p>
      </section>
    );
  }

  const attachmentsDialog = (
    <JournalEntryAttachmentsDialog
      entryId={attachmentsEntryId}
      onDismiss={() => setAttachmentsEntryId(null)}
    />
  );

  if (view === "form") {
    if (formLoading) {
      return (
        <>
          {attachmentsDialog}
          <p>{editingId == null ? "Loading…" : "Loading entry…"}</p>
        </>
      );
    }
    if (formLoadError) {
      return (
        <>
          {attachmentsDialog}
          <div className="card">
            <p className="error" role="alert">
              {formLoadError}
            </p>
            <button type="button" className="button-secondary" onClick={handleCancelForm}>
              Back to list
            </button>
          </div>
        </>
      );
    }
    return (
      <>
        {attachmentsDialog}
        <section className="card journal-card-wide">
          <JournalEntryForm
            key={editingId ?? "new"}
            mode={editingId == null ? "create" : "edit"}
            accounts={accounts}
            parties={parties}
            initialEntryDate={formEntryDate}
            initialSummary={formSummary}
            initialDescription={formDescription}
            reviewMessages={formReviewMessages}
            entryId={editingId}
            onReviewMessagesChanged={() => void reloadReviewMessagesForEditor()}
            initialLines={formLines}
            onSubmit={handleSubmit}
            onCancel={handleCancelForm}
            onOpenAttachments={
              editingId != null ? () => setAttachmentsEntryId(editingId) : undefined
            }
            chequeLinkChoices={formChequeChoices}
            initialChequeId={formInitialChequeId}
          />
        </section>
      </>
    );
  }

  return (
    <>
      {attachmentsDialog}
      <section className="card journal-card-wide">
      {accounts.length === 0 && (
        <p className="muted banner-info">
          Add at least two accounts under <strong>Accounts</strong> before posting journal lines.
        </p>
      )}
      <div className="journal-list-toolbar">
        <h2>Journal entries</h2>
        <button type="button" onClick={() => void openCreate()} disabled={accounts.length < 2}>
          New entry
        </button>
      </div>

      <div className="journal-filters">
        <label>
          From date
          <input
            aria-label="Filter from date"
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
        </label>
        <label>
          To date
          <input
            aria-label="Filter to date"
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />
        </label>
        <label className="checkbox">
          <input
            aria-label="Show entries needing review only"
            type="checkbox"
            checked={needsReviewOnly}
            onChange={(e) => setNeedsReviewOnly(e.target.checked)}
          />
          Needs review only
        </label>
      </div>

      {listLoading && entries.length === 0 && <p>Loading…</p>}
      {listError && (
        <p className="error" role="alert">
          {listError}
        </p>
      )}

      {!listError && entries.length === 0 && !listLoading && <p>No journal entries in this range.</p>}

      {entries.length > 0 && (
        <table className="journal-entry-list">
          <thead>
            <tr>
              <th>Date</th>
              <th>Summary</th>
              <th>Parties</th>
              <th>Debit account</th>
              <th>Credit account</th>
              <th className="journal-list-amount">Amount</th>
              <th aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {entries.map((row) => (
              <tr key={row.id}>
                <td>{row.entry_date}</td>
                <td>{row.summary}</td>
                <td>{row.requires_review ? "Yes" : "—"}</td>
                <td>{row.party_labels}</td>
                <td>{row.debit_side_label}</td>
                <td>{row.credit_side_label}</td>
                <td className="journal-list-amount">{row.amount}</td>
                <td>
                  <div className="journal-list-actions">
                    <TableRowIconButton
                      type="button"
                      onClick={() => void openEdit(row.id)}
                      title={`Edit journal entry: ${row.summary}`}
                      aria-label={`Edit journal entry: ${row.summary}`}
                    >
                      <Pencil size={18} strokeWidth={2} aria-hidden />
                    </TableRowIconButton>
                    <TableRowIconButton
                      type="button"
                      onClick={() => setAttachmentsEntryId(row.id)}
                      title={`Attachments for ${row.summary}`}
                      aria-label={`Attachments for ${row.summary}`}
                    >
                      <Paperclip size={18} strokeWidth={2} aria-hidden />
                    </TableRowIconButton>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {hasMore && (
        <button
          type="button"
          className="button-secondary"
          disabled={listLoading}
          onClick={() => void loadMore()}
        >
          {listLoading ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
    </>
  );
}
