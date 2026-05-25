import {
  cycleSortKeys,
  primarySortKey,
  sameSortKeys,
  toSortParams,
  type SortDirection,
  type SortKey,
} from "./registerSort";

export type ChequeSortDirection = SortDirection;
export type ChequeSortKey = SortKey;

export const CHEQUE_REGISTER_SORT_FIELDS = {
  status: "status",
  chequeNumber: "cheque_number",
  summary: "summary",
  issueDate: "issue_date",
  clearedDate: "cleared_date",
  amount: "amount",
  creditAccountId: "credit_account_id",
  debitAccountId: "debit_account_id",
  partyId: "party_id",
} as const;

export type ChequeRegisterSortField =
  (typeof CHEQUE_REGISTER_SORT_FIELDS)[keyof typeof CHEQUE_REGISTER_SORT_FIELDS];

export { cycleSortKeys, primarySortKey, toSortParams, sameSortKeys };
