import { describe, expect, it } from "vitest";

import {
  abbreviateFiscalYearEndSegment,
  proposeDuplicateAccrualPlanName,
  shiftAccrualPlanDatesByOneYear,
} from "./accrualPlanDuplicate";

describe("abbreviateFiscalYearEndSegment", () => {
  it("abbreviates 2029–2030 as 30", () => {
    expect(abbreviateFiscalYearEndSegment(2029, 2030)).toBe("30");
  });

  it("abbreviates 2028–2029 as 9", () => {
    expect(abbreviateFiscalYearEndSegment(2028, 2029)).toBe("9");
  });

  it("keeps full years when abbreviation would be ambiguous", () => {
    expect(abbreviateFiscalYearEndSegment(2028, 2029)).toBe("9");
    expect(abbreviateFiscalYearEndSegment(2028, 2030)).not.toBe("0");
  });
});

describe("proposeDuplicateAccrualPlanName", () => {
  it("advances fiscal pair 2028/9 to 2029/30", () => {
    expect(proposeDuplicateAccrualPlanName("Rent 2028/9", [])).toBe("Rent 2029/30");
  });

  it("advances full fiscal pair 2028/2029 to 2029/2030", () => {
    expect(proposeDuplicateAccrualPlanName("Plan 2028/2029", [])).toBe("Plan 2029/2030");
  });

  it("prefers rightmost fiscal pair over standalone year", () => {
    expect(proposeDuplicateAccrualPlanName("2027 Budget 2028/9 tail 2020", [])).toBe(
      "2027 Budget 2029/30 tail 2020",
    );
  });

  it("prefers fiscal pair over standalone year in the same name", () => {
    expect(proposeDuplicateAccrualPlanName("2029 plan 2028/9", [])).toBe("2029 plan 2029/30");
  });

  it("advances rightmost standalone year when no pair", () => {
    expect(proposeDuplicateAccrualPlanName("Budget 2029", [])).toBe("Budget 2030");
  });

  it("uses rightmost standalone year when multiple exist", () => {
    expect(proposeDuplicateAccrualPlanName("2027 and 2028 budget 2029", [])).toBe(
      "2027 and 2028 budget 2030",
    );
  });

  it("does not treat year digits inside a fiscal pair as standalone", () => {
    expect(proposeDuplicateAccrualPlanName("FY 2028/2029", [])).toBe("FY 2029/2030");
  });

  it("appends - Copy when advanced name collides", () => {
    expect(proposeDuplicateAccrualPlanName("Budget 2029", ["Budget 2030"])).toBe("Budget 2029 - Copy");
  });

  it("appends - Copy (n) when - Copy also exists", () => {
    const taken = ["Budget 2030", "Budget 2029 - Copy"];
    expect(proposeDuplicateAccrualPlanName("Budget 2029", taken)).toBe("Budget 2029 - Copy (1)");
  });

  it("serialises copy suffix until unique", () => {
    const taken = ["Budget 2030", "Budget 2029 - Copy", "Budget 2029 - Copy (1)"];
    expect(proposeDuplicateAccrualPlanName("Budget 2029", taken)).toBe("Budget 2029 - Copy (2)");
  });

  it("uses copy suffix when year rules do not change the name uniquely", () => {
    expect(proposeDuplicateAccrualPlanName("Evergreen Plan", ["Evergreen Plan"])).toBe(
      "Evergreen Plan - Copy",
    );
  });

  it("matches names case-sensitively", () => {
    expect(proposeDuplicateAccrualPlanName("Budget 2029", ["budget 2030"])).toBe("Budget 2030");
    expect(proposeDuplicateAccrualPlanName("Budget 2029", ["Budget 2030"])).toBe("Budget 2029 - Copy");
  });
});

describe("shiftAccrualPlanDatesByOneYear", () => {
  it("adds one calendar year to start and end", () => {
    expect(shiftAccrualPlanDatesByOneYear("2026-01-15", "2026-12-31")).toEqual({
      start: "2027-01-15",
      end: "2027-12-31",
    });
  });

  it("clamps 29 Feb to last day of February in non-leap year", () => {
    expect(shiftAccrualPlanDatesByOneYear("2024-02-29", "2024-02-29")).toEqual({
      start: "2025-02-28",
      end: "2025-02-28",
    });
  });

  it("clamps 31 Jan style dates when target month is shorter", () => {
    expect(shiftAccrualPlanDatesByOneYear("2025-01-31", "2025-03-31")).toEqual({
      start: "2026-01-31",
      end: "2026-03-31",
    });
    expect(shiftAccrualPlanDatesByOneYear("2024-08-31", "2024-08-31")).toEqual({
      start: "2025-08-31",
      end: "2025-08-31",
    });
  });
});
