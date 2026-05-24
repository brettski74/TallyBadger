import { describe, expect, it } from "vitest";

import {
  CHEQUE_REGISTER_SORT_FIELDS,
  cycleSortKeys,
  primarySortKey,
  toSortParams,
  type ChequeSortKey,
} from "./chequeRegisterSort";

describe("cycleSortKeys", () => {
  it("prepends asc when the clicked column is not primary", () => {
    expect(cycleSortKeys([], CHEQUE_REGISTER_SORT_FIELDS.clearedDate)).toEqual([
      { field: "cleared_date", direction: "asc" },
    ]);
  });

  it("prepends asc and demotes an existing secondary key", () => {
    const current: ChequeSortKey[] = [{ field: "cleared_date", direction: "desc" }];
    expect(cycleSortKeys(current, CHEQUE_REGISTER_SORT_FIELDS.amount)).toEqual([
      { field: "amount", direction: "asc" },
      { field: "cleared_date", direction: "desc" },
    ]);
  });

  it("removes and prepends when the clicked column was secondary", () => {
    const current: ChequeSortKey[] = [
      { field: "amount", direction: "asc" },
      { field: "cleared_date", direction: "desc" },
    ];
    expect(cycleSortKeys(current, CHEQUE_REGISTER_SORT_FIELDS.clearedDate)).toEqual([
      { field: "cleared_date", direction: "asc" },
      { field: "amount", direction: "asc" },
    ]);
  });

  it("cycles primary asc to desc", () => {
    const current: ChequeSortKey[] = [{ field: "amount", direction: "asc" }];
    expect(cycleSortKeys(current, CHEQUE_REGISTER_SORT_FIELDS.amount)).toEqual([
      { field: "amount", direction: "desc" },
    ]);
  });

  it("cycles primary desc to unsorted and promotes the next key", () => {
    const current: ChequeSortKey[] = [
      { field: "amount", direction: "desc" },
      { field: "cleared_date", direction: "desc" },
    ];
    expect(cycleSortKeys(current, CHEQUE_REGISTER_SORT_FIELDS.amount)).toEqual([
      { field: "cleared_date", direction: "desc" },
    ]);
  });

  it("clears sort when removing the only primary key", () => {
    const current: ChequeSortKey[] = [{ field: "cleared_date", direction: "desc" }];
    expect(cycleSortKeys(current, CHEQUE_REGISTER_SORT_FIELDS.clearedDate)).toEqual([]);
  });
});

describe("toSortParams", () => {
  it("serializes stacked keys for the API", () => {
    expect(
      toSortParams([
        { field: "amount", direction: "asc" },
        { field: "cleared_date", direction: "desc" },
      ]),
    ).toEqual(["amount:asc", "cleared_date:desc"]);
  });
});

describe("primarySortKey", () => {
  it("returns null for an empty list", () => {
    expect(primarySortKey([])).toBeNull();
  });

  it("returns the first key when present", () => {
    expect(
      primarySortKey([
        { field: "amount", direction: "asc" },
        { field: "cleared_date", direction: "desc" },
      ]),
    ).toEqual({ field: "amount", direction: "asc" });
  });
});
