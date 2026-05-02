import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import type { Party } from "../api/parties";
import { SettlementsSection } from "./SettlementsSection";

afterEach(() => {
  vi.restoreAllMocks();
});

const accounts: Account[] = [
  { id: 1, name: "Cash", type: "asset", is_active: true, created_at: "", updated_at: "" },
  { id: 2, name: "Accounts Receivable", type: "asset", is_active: true, created_at: "", updated_at: "" },
  { id: 3, name: "Accounts Payable", type: "liability", is_active: true, created_at: "", updated_at: "" },
  { id: 4, name: "Unearned Revenue", type: "liability", is_active: true, created_at: "", updated_at: "" },
];

const parties: Party[] = [
  { id: 1, name: "Acme Yard Maintenance", role: "customer", is_active: true, created_at: "", updated_at: "" },
];

describe("SettlementsSection", () => {
  it("shows obligation date/summary and auto-allocates earliest obligations", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
            {
              id: 10,
              party_id: 1,
              source_entry_id: 100,
              source_entry_date: "2026-01-01",
              source_entry_summary: "January accrual",
              obligation_type: "receivable",
              status: "open",
              original_amount: "100.00",
              open_amount: "100.00",
            },
            {
              id: 11,
              party_id: 1,
              source_entry_id: 101,
              source_entry_date: "2026-02-01",
              source_entry_summary: "February accrual",
              obligation_type: "receivable",
              status: "open",
              original_amount: "75.00",
              open_amount: "75.00",
            },
            {
              id: 12,
              party_id: 1,
              source_entry_id: 102,
              source_entry_date: "2126-03-01",
              source_entry_summary: "Far future accrual",
              obligation_type: "receivable",
              status: "open",
              original_amount: "300.00",
              open_amount: "300.00",
            },
        ]),
        { status: 200 },
      ),
    );

    render(<SettlementsSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText("Party"), "1");
    await user.clear(screen.getByLabelText("Amount"));
    await user.type(screen.getByLabelText("Amount"), "425.00");

    expect(await screen.findByText("January accrual")).toBeInTheDocument();
    expect(screen.getByText("2026-01-01")).toBeInTheDocument();
    expect(screen.getByLabelText("Allocate obligation 10")).toHaveValue("100.00");
    expect(screen.getByLabelText("Allocate obligation 11")).toHaveValue("75.00");
    expect(screen.getByLabelText("Allocate obligation 12")).toHaveValue("250.00");
    expect(screen.getByText("future")).toBeInTheDocument();
  });
});
