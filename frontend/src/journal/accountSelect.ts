import type { Account } from "../api/accounts";

/** Active accounts plus any inactive account already referenced on the current entry lines. */
export function accountsForJournalLinePickers(
  allAccounts: Account[],
  lineAccountIds: number[],
): Account[] {
  const onLine = new Set(lineAccountIds);
  return allAccounts.filter((a) => a.is_active || onLine.has(a.id));
}
