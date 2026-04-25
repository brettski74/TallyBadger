import { describe, expect, it } from "vitest";

import type { Account } from "../api/accounts";
import { accountsForJournalLinePickers } from "./accountSelect";

const base = (overrides: Partial<Account>): Account => ({
  id: 1,
  name: "A",
  type: "asset",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

describe("accountsForJournalLinePickers", () => {
  it("includes active accounts", () => {
    const all = [base({ id: 1, name: "Cash", is_active: true })];
    expect(accountsForJournalLinePickers(all, []).map((a) => a.id)).toEqual([1]);
  });

  it("excludes inactive accounts unless referenced on a line", () => {
    const all = [
      base({ id: 1, name: "Old", is_active: false }),
      base({ id: 2, name: "New", is_active: true }),
    ];
    expect(accountsForJournalLinePickers(all, []).map((a) => a.id)).toEqual([2]);
    expect(accountsForJournalLinePickers(all, [1]).map((a) => a.id).sort()).toEqual([1, 2]);
  });
});
