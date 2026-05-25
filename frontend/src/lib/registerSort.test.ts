import { describe, expect, it } from "vitest";

import { cycleSortKeys, primarySortKey, sameSortKeys, toSortParams } from "./registerSort";

describe("registerSort", () => {
  it("cycles primary asc to desc", () => {
    expect(cycleSortKeys([{ field: "amount", direction: "asc" }], "amount")).toEqual([
      { field: "amount", direction: "desc" },
    ]);
  });

  it("clears sort when removing the only primary key", () => {
    expect(cycleSortKeys([{ field: "amount", direction: "desc" }], "amount")).toEqual([]);
  });

  it("serializes stacked keys for the API", () => {
    expect(
      toSortParams([
        { field: "amount", direction: "asc" },
        { field: "entry_date", direction: "desc" },
      ]),
    ).toEqual(["amount:asc", "entry_date:desc"]);
  });

  it("compares sort key lists for preset equivalence", () => {
    const a = [{ field: "summary", direction: "asc" as const }];
    const b = [{ field: "summary", direction: "asc" as const }];
    expect(sameSortKeys(a, b)).toBe(true);
    expect(sameSortKeys(a, [{ field: "summary", direction: "desc" }])).toBe(false);
  });

  it("returns null primary for empty list", () => {
    expect(primarySortKey([])).toBeNull();
  });
});
