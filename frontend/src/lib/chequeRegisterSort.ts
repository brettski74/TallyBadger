export type ChequeSortDirection = "asc" | "desc";

export interface ChequeSortKey {
  field: string;
  direction: ChequeSortDirection;
}

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

export function primarySortKey(keys: ChequeSortKey[]): ChequeSortKey | null {
  return keys.length > 0 ? keys[0] : null;
}

export function toSortParams(keys: ChequeSortKey[]): string[] {
  return keys.map(({ field, direction }) => `${field}:${direction}`);
}

export function cycleSortKeys(current: ChequeSortKey[], clickedField: string): ChequeSortKey[] {
  const index = current.findIndex((key) => key.field === clickedField);
  const isPrimary = index === 0;

  if (!isPrimary) {
    const withoutClicked = current.filter((key) => key.field !== clickedField);
    return [{ field: clickedField, direction: "asc" }, ...withoutClicked];
  }

  const primary = current[0];
  if (primary.direction === "asc") {
    return [{ field: clickedField, direction: "desc" }, ...current.slice(1)];
  }

  return current.slice(1);
}
