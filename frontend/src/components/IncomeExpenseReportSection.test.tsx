import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { IncomeExpenseReportSection } from "./IncomeExpenseReportSection";

const fetchMock = vi.fn();

vi.mock("../api/incomeExpenseReport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/incomeExpenseReport")>();
  return {
    ...actual,
    fetchIncomeExpenseReport: (p: unknown) => fetchMock(p),
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("IncomeExpenseReportSection", () => {
  it("loads report with preset and shows totals", async () => {
    fetchMock.mockResolvedValue({
      report_schema_version: 1,
      period: { start_date: "2026-01-01", end_date: "2026-05-05" },
      currency_label: "single_currency_numeric_18_2",
      preset: "current_year_to_date",
      exclude_zero_balance_accounts: false,
      revenue_accounts: [{ account_id: 1, account_name: "Rent", account_type: "revenue", is_active: true, amount: "100.00" }],
      expense_accounts: [],
      total_revenue: "100.00",
      total_expense: "0.00",
      net_income: "100.00",
    });

    render(<IncomeExpenseReportSection />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Run report" }));

    expect(await screen.findByText("Total revenue")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "100.00" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Rent/ })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.objectContaining({
        preset: "current_year_to_date",
        excludeZeroBalanceAccounts: false,
      }),
    );
  });

  it("requests custom date range", async () => {
    fetchMock.mockResolvedValue({
      report_schema_version: 1,
      period: { start_date: "2026-02-01", end_date: "2026-02-28" },
      currency_label: "single_currency_numeric_18_2",
      preset: null,
      exclude_zero_balance_accounts: false,
      revenue_accounts: [],
      expense_accounts: [],
      total_revenue: "0.00",
      total_expense: "0.00",
      net_income: "0.00",
    });

    render(<IncomeExpenseReportSection />);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Period"), "custom");
    await user.type(screen.getByLabelText("Start"), "2026-02-01");
    await user.type(screen.getByLabelText("End"), "2026-02-28");
    await user.click(screen.getByRole("button", { name: "Run report" }));

    expect(fetchMock).toHaveBeenCalledWith(
      expect.objectContaining({
        startDate: "2026-02-01",
        endDate: "2026-02-28",
        excludeZeroBalanceAccounts: false,
      }),
    );
  });
});
