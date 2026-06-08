import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import { AccountStatementSettingsDialog } from "./AccountStatementSettingsDialog";
import { AccountStatementReportDialog } from "./AccountStatementReportDialog";

const fetchMock = vi.fn();

vi.mock("../api/accountStatementReport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/accountStatementReport")>();
  return {
    ...actual,
    fetchAccountStatementReport: (p: unknown) => fetchMock(p),
  };
});

vi.mock("../lib/priorCompletedCalendarMonth", () => ({
  priorCompletedCalendarMonthRange: () => ({
    startDate: "2026-05-01",
    endDate: "2026-05-31",
  }),
}));

const sampleAccount: Account = {
  id: 3,
  name: "Cash",
  type: "asset",
  is_active: true,
};

const sampleReport = {
  report_schema_version: 1 as const,
  account: { account_id: 3, account_name: "Cash", is_active: true },
  period: { start_date: "2026-05-01", end_date: "2026-05-31" },
  currency_label: "single_currency_numeric_18_2",
  balance_forward: "0.00",
  closing_balance: "10.00",
  rows: [
    {
      row_kind: "balance_forward" as const,
      entry_date: "2026-05-01",
      summary: "Balance forward",
      counterparty_account: null,
      party: null,
      debit: null,
      credit: null,
      balance: "0.00",
      entry_id: null,
    },
    {
      row_kind: "activity" as const,
      entry_date: "2026-05-10",
      summary: "deposit",
      counterparty_account: "Revenue",
      party: "-- None --",
      debit: "10.00",
      credit: null,
      balance: "10.00",
      entry_id: 1,
    },
    {
      row_kind: "closing_balance" as const,
      entry_date: "2026-05-31",
      summary: "Closing balance",
      counterparty_account: null,
      party: null,
      debit: null,
      credit: null,
      balance: "10.00",
      entry_id: null,
    },
  ],
};

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.open = false;
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AccountStatementSettingsDialog", () => {
  it("defaults start and end dates to the prior completed calendar month", () => {
    render(
      <AccountStatementSettingsDialog
        open
        account={sampleAccount}
        onDismiss={() => {}}
        onReportLoaded={() => {}}
      />,
    );

    expect(screen.getByLabelText("Start date")).toHaveValue("2026-05-01");
    expect(screen.getByLabelText("End date")).toHaveValue("2026-05-31");
  });

  it("loads the report when Run is clicked", async () => {
    fetchMock.mockResolvedValue(sampleReport);
    const onReportLoaded = vi.fn();

    render(
      <AccountStatementSettingsDialog
        open
        account={sampleAccount}
        onDismiss={() => {}}
        onReportLoaded={onReportLoaded}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Run" }));

    expect(fetchMock).toHaveBeenCalledWith({
      accountId: 3,
      startDate: "2026-05-01",
      endDate: "2026-05-31",
    });
    expect(onReportLoaded).toHaveBeenCalled();
  });
});

describe("AccountStatementReportDialog", () => {
  it("renders statement column headers and title", () => {
    render(
      <AccountStatementReportDialog
        open
        report={sampleReport}
        params={{ accountId: 3, startDate: "2026-05-01", endDate: "2026-05-31" }}
        onDismiss={() => {}}
      />,
    );

    expect(screen.getByRole("heading", { name: "Cash Statement" })).toBeInTheDocument();
    expect(screen.getByText("Start Date: 2026-05-01")).toBeInTheDocument();
    expect(screen.getByText("End Date: 2026-05-31")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Entry date" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Summary" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Debit" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Export CSV" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Export PDF" })).toBeInTheDocument();
  });
});
