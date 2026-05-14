import type { Account } from "../api/accounts";

/** Shape needed to build account options for one journal line. */
export interface LineAccountPickerInput {
  account_id: number | "";
  /** From GET /journal-entries/:id when the chart row is missing or stale. */
  account_name?: string;
}

function parseOptionalAccountIdString(s: string): number | null {
  const t = s.trim();
  if (t === "") {
    return null;
  }
  const n = Number(t);
  return Number.isFinite(n) && n >= 1 ? n : null;
}

/**
 * Options for a single journal line: every active account plus this line's
 * current draft selection and (when editing) the account id that was loaded for
 * the line so a temporarily changed inactive reference can be chosen again.
 */
export function accountsForLinePicker(
  allAccounts: Account[],
  line: LineAccountPickerInput,
  loadedAccountId: number | null = null,
): Account[] {
  const byId = new Map(allAccounts.map((a) => [a.id, a]));
  const selectedId = typeof line.account_id === "number" && line.account_id > 0 ? line.account_id : null;
  const keepIds = new Set<number>();
  if (selectedId !== null) {
    keepIds.add(selectedId);
  }
  if (loadedAccountId !== null && loadedAccountId > 0) {
    keepIds.add(loadedAccountId);
  }

  const out: Account[] = [];
  for (const a of allAccounts) {
    if (a.is_active || keepIds.has(a.id)) {
      out.push(a);
    }
  }

  const hint = line.account_name?.trim();
  if (selectedId !== null && hint && !byId.has(selectedId)) {
    out.push({
      id: selectedId,
      name: hint,
      type: "asset",
      is_active: false,
      created_at: "1970-01-01T00:00:00Z",
      updated_at: "1970-01-01T00:00:00Z",
    });
  }

  return out.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Configuration / settings pickers: active rows in the candidate list, plus
 * the current draft id and the last-loaded baseline id (so an inactive saved
 * value stays visible until a successful save updates the baseline).
 */
export function accountsForSettingPicker(
  typeFilteredAccounts: Account[],
  selectedAccountIdString: string,
  baselineAccountIdString: string = "",
): Account[] {
  const selectedId = parseOptionalAccountIdString(selectedAccountIdString);
  const baselineId = parseOptionalAccountIdString(baselineAccountIdString);
  const keep = new Set<number>();
  if (selectedId !== null) {
    keep.add(selectedId);
  }
  if (baselineId !== null) {
    keep.add(baselineId);
  }
  if (keep.size === 0) {
    return typeFilteredAccounts.filter((a) => a.is_active);
  }
  return typeFilteredAccounts.filter((a) => a.is_active || keep.has(a.id));
}
