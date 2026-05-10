import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BalanceSheetReportSection } from "./BalanceSheetReportSection";

const fetchMock = vi.fn();

vi.mock("../api/balanceSheetReport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/balanceSheetReport")>();
  return {
    ...actual,
    fetchBalanceSheetReport: (p: unknown) => fetchMock(p),
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("BalanceSheetReportSection", () => {
  it("loads report and renders totals plus export buttons", async () => {
    fetchMock.mockResolvedValue({
      report_schema_version: 1,
      period: { as_of_date: "2026-01-31" },
      currency_label: "single_currency_numeric_18_2",
      preset: "today",
      exclude_requires_review: false,
      assets: {
        section: "assets",
        label: "Assets",
        accounts: [{ account_id: 1, account_name: "Cash", account_type: "asset", is_active: true, is_computed: false, amount: "1450.00" }],
        total: "1450.00",
      },
      liabilities: {
        section: "liabilities",
        label: "Liabilities",
        accounts: [{ account_id: 2, account_name: "Loan", account_type: "liability", is_active: true, is_computed: false, amount: "200.00" }],
        total: "200.00",
      },
      equity: {
        section: "equity",
        label: "Equity",
        accounts: [
          { account_id: 3, account_name: "Owner Contributions", account_type: "equity", is_active: true, is_computed: false, amount: "1000.00" },
          { account_id: null, account_name: "Retained Earnings", account_type: "computed_equity", is_active: null, is_computed: true, amount: "250.00" },
        ],
        total: "1250.00",
      },
      balance_check: {
        assets_total: "1450.00",
        liabilities_total: "200.00",
        equity_total: "1250.00",
        liabilities_plus_equity: "1450.00",
        is_balanced: true,
        difference: "0.00",
      },
    });

    render(<BalanceSheetReportSection />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Run report" }));

    expect(await screen.findAllByText("Assets total")).not.toHaveLength(0);
    const retainedRow = screen.getByRole("row", { name: /Retained Earnings/ });
    expect(within(retainedRow).getByRole("cell", { name: "$250.00" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Balance check" })).toHaveTextContent("Difference");
    expect(screen.getByRole("link", { name: "Export CSV" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Export PDF" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.objectContaining({ preset: "today", excludeRequiresReview: false }));
  });

  it("requests custom as-of date", async () => {
    fetchMock.mockResolvedValue({
      report_schema_version: 1,
      period: { as_of_date: "2026-02-28" },
      currency_label: "single_currency_numeric_18_2",
      preset: null,
      exclude_requires_review: false,
      assets: { section: "assets", label: "Assets", accounts: [], total: "0.00" },
      liabilities: { section: "liabilities", label: "Liabilities", accounts: [], total: "0.00" },
      equity: {
        section: "equity",
        label: "Equity",
        accounts: [{ account_id: null, account_name: "Retained Earnings", account_type: "computed_equity", is_active: null, is_computed: true, amount: "0.00" }],
        total: "0.00",
      },
      balance_check: {
        assets_total: "0.00",
        liabilities_total: "0.00",
        equity_total: "0.00",
        liabilities_plus_equity: "0.00",
        is_balanced: true,
        difference: "0.00",
      },
    });

    render(<BalanceSheetReportSection />);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("As of"), "custom");
    await user.type(screen.getByLabelText("Date"), "2026-02-28");
    await user.click(screen.getByRole("button", { name: "Run report" }));

    expect(fetchMock).toHaveBeenCalledWith(
      expect.objectContaining({
        asOfDate: "2026-02-28",
        excludeRequiresReview: false,
      }),
    );
  });
});
