import {
  cycleSortKeys,
  primarySortKey,
  sameSortKeys,
  toSortParams,
  type SortDirection,
  type SortKey,
} from "./registerSort";

export type JournalSortDirection = SortDirection;
export type JournalSortKey = SortKey;

export const JOURNAL_REGISTER_SORT_FIELDS = {
  entryDate: "entry_date",
  summary: "summary",
  requiresReview: "requires_review",
  partyLabels: "party_labels",
  debitLabel: "debit_label",
  creditLabel: "credit_label",
  amount: "amount",
} as const;

export type JournalRegisterSortField =
  (typeof JOURNAL_REGISTER_SORT_FIELDS)[keyof typeof JOURNAL_REGISTER_SORT_FIELDS];

export { cycleSortKeys, primarySortKey, sameSortKeys, toSortParams };
