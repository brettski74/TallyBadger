import { describe, expect, it } from "vitest";

import type { Account } from "../api/accounts";
import { accountsForLinePicker, accountsForSettingPicker } from "./accountSelect";

const base = (overrides: Partial<Account>): Account => ({
  id: 1,
  name: "A",
  type: "asset",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

describe("accountsForLinePicker", () => {
  it("includes active accounts when line has no account selected", () => {
    const all = [
      base({ id: 1, name: "Cash", is_active: true }),
      base({ id: 2, name: "Old", is_active: false }),
    ];
    expect(accountsForLinePicker(all, { account_id: "" }).map((a) => a.id)).toEqual([1]);
  });

  it("includes inactive account when this line selects it", () => {
    const all = [
      base({ id: 1, name: "Cash", is_active: true }),
      base({ id: 2, name: "Retired", is_active: false }),
    ];
    expect(accountsForLinePicker(all, { account_id: "" }).map((a) => a.id)).toEqual([1]);
    expect(accountsForLinePicker(all, { account_id: 1 }).map((a) => a.id).sort()).toEqual([1]);
    expect(accountsForLinePicker(all, { account_id: 2 }).map((a) => a.id).sort()).toEqual([1, 2]);
  });

  it("keeps an inactive loaded id visible after the draft account changes away", () => {
    const all = [
      base({ id: 1, name: "Cash", is_active: true }),
      base({ id: 2, name: "Retired", is_active: false }),
    ];
    const options = accountsForLinePicker(all, { account_id: 1 }, 2).map((a) => a.id).sort();
    expect(options).toEqual([1, 2]);
  });

  it("adds a stub row when account_id is set with a name hint but id is missing from chart", () => {
    const all = [base({ id: 1, name: "Cash", is_active: true })];
    const out = accountsForLinePicker(all, { account_id: 99, account_name: "Ghost" });
    expect(out.map((a) => [a.id, a.name, a.is_active])).toEqual([
      [1, "Cash", true],
      [99, "Ghost", false],
    ]);
  });
});

describe("accountsForSettingPicker", () => {
  const assets = [
    base({ id: 1, name: "Cash", is_active: true }),
    base({ id: 2, name: "Stale AR", is_active: false }),
  ];

  it("lists only active accounts when nothing is selected", () => {
    expect(accountsForSettingPicker(assets, "", "").map((a) => a.id)).toEqual([1]);
  });

  it("includes inactive id when it is the current selection", () => {
    expect(accountsForSettingPicker(assets, "2", "").map((a) => a.id).sort()).toEqual([1, 2]);
  });

  it("includes inactive baseline when draft moved to another id", () => {
    expect(accountsForSettingPicker(assets, "1", "2").map((a) => a.id).sort()).toEqual([1, 2]);
  });
});
