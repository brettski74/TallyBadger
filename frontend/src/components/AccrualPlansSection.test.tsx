import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import type { Party } from "../api/parties";
import { AccrualPlansSection } from "./AccrualPlansSection";

afterEach(() => {
  vi.restoreAllMocks();
});

const accounts: Account[] = [
  { id: 1, name: "Accounts Receivable", type: "asset", is_active: true, created_at: "", updated_at: "" },
  { id: 2, name: "Rent Revenue", type: "revenue", is_active: true, created_at: "", updated_at: "" },
  { id: 3, name: "Accounts Payable", type: "liability", is_active: true, created_at: "", updated_at: "" },
  { id: 4, name: "Repairs Expense", type: "expense", is_active: true, created_at: "", updated_at: "" },
];

const parties: Party[] = [
  {
    id: 1,
    name: "Acme Yard Maintenance",
    role: "customer",
    is_active: true,
    match_patterns: [],
    created_at: "",
    updated_at: "",
  },
];

describe("AccrualPlansSection", () => {
  it("previews then creates a plan", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ plans: [] }), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              entry_date: "2026-01-01",
              summary: "Plan 2026-01",
              description: null,
              lines: [
                { account_id: 1, party_id: 1, amount: "100.00" },
                { account_id: 2, party_id: 1, amount: "-100.00" },
              ],
            },
          ]),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: 11,
            name: "Rent Plan",
            direction: "revenue",
            party_id: 1,
            target_account_id: 2,
            bridge_account_id: 1,
            frequency: "monthly_day",
            start_date: "2026-01-01",
            end_date: "2026-01-31",
            amount: "100.00",
            summary_template: "{plan} {month}",
            description_template: null,
            day_of_week: null,
            day_of_month: 1,
            month_of_year: null,
            business_day_adjust: false,
            created_at: "",
            updated_at: "",
          }),
          { status: 201 },
        ),
      );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Target account"), "2");
    await user.selectOptions(screen.getByLabelText("Bridge account"), "1");
    await user.clear(screen.getByLabelText("Plan amount"));
    await user.type(screen.getByLabelText("Plan amount"), "100.00");
    await user.click(screen.getByRole("button", { name: "Preview entries" }));

    expect(await screen.findByText("Plan 2026-01")).toBeInTheDocument();
    const previewTable = screen.getByRole("table", { name: "Accrual preview" });
    expect(within(previewTable).getByText("Acme Yard Maintenance")).toBeInTheDocument();
    expect(within(previewTable).getByText("Accounts Receivable")).toBeInTheDocument();
    expect(within(previewTable).getByText("Rent Revenue")).toBeInTheDocument();
    expect(within(previewTable).getByText("100.00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create plan" }));

    await waitFor(() => expect(screen.getByText("Rent Plan")).toBeInTheDocument());
  });

  it("shows a clear message when party is not selected on preview", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ plans: [] }), { status: 200 }),
    );
    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Target account"), "2");
    await user.selectOptions(screen.getByLabelText("Bridge account"), "1");
    await user.click(screen.getByRole("button", { name: "Preview entries" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Select a party.");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(String(fetchSpy.mock.calls[0]?.[0])).not.toContain("/preview");
  });

  it("prevents preview when account types do not match direction", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ plans: [] }), { status: 200 }),
    );
    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Plan name"), "Bad Revenue Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Target account"), "2");
    await user.selectOptions(screen.getByLabelText("Bridge account"), "1");
    await user.selectOptions(screen.getByLabelText("Plan direction"), "expense");
    await user.click(screen.getByRole("button", { name: "Preview entries" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Expense plans require an expense target account.",
    );
  });
});
