import { describe, expect, it } from "vitest";

import { priorCompletedCalendarMonthRange } from "./priorCompletedCalendarMonth";

describe("priorCompletedCalendarMonthRange", () => {
  it("returns the prior full calendar month in local time", () => {
    const range = priorCompletedCalendarMonthRange(new Date(2026, 5, 4));
    expect(range).toEqual({ startDate: "2026-05-01", endDate: "2026-05-31" });
  });

  it("handles January by using December of the prior year", () => {
    const range = priorCompletedCalendarMonthRange(new Date(2026, 0, 15));
    expect(range).toEqual({ startDate: "2025-12-01", endDate: "2025-12-31" });
  });
});
