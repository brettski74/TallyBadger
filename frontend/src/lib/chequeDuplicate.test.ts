import { describe, expect, it } from "vitest";

import { addOneCalendarMonth, proposeNextChequeNumber } from "./chequeDuplicate";

describe("proposeNextChequeNumber", () => {
  it("returns 1 when no cheques exist on the credit account", () => {
    expect(proposeNextChequeNumber([])).toBe(1);
  });

  it("returns max cheque_number plus 1 across any status", () => {
    expect(
      proposeNextChequeNumber([
        { cheque_number: 3 },
        { cheque_number: 12 },
        { cheque_number: 7 },
      ]),
    ).toBe(13);
  });
});

describe("addOneCalendarMonth", () => {
  it("advances a mid-month date by one month", () => {
    expect(addOneCalendarMonth("2026-05-15")).toBe("2026-06-15");
  });

  it("clamps 31 January to the last day of February", () => {
    expect(addOneCalendarMonth("2026-01-31")).toBe("2026-02-28");
  });

  it("clamps 31 January to 29 February in a leap year", () => {
    expect(addOneCalendarMonth("2024-01-31")).toBe("2024-02-29");
  });

  it("rolls year when advancing from December", () => {
    expect(addOneCalendarMonth("2026-12-10")).toBe("2027-01-10");
  });
});
