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
  {
    id: 2,
    name: "Beta Property Co",
    role: "customer",
    is_active: true,
    match_patterns: [],
    created_at: "",
    updated_at: "",
  },
];

const emptyListBody = {
  plans: [],
  filter_options: { party_ids: [], target_account_ids: [], bridge_account_ids: [] },
};

function listPlansResponse(plans: unknown[] = [], filterOptions?: Partial<typeof emptyListBody.filter_options>) {
  return new Response(
    JSON.stringify({
      plans,
      filter_options: {
        party_ids: plans.length ? [1, 2] : [],
        target_account_ids: plans.length ? [2, 4] : [],
        bridge_account_ids: plans.length ? [1, 3] : [],
        ...filterOptions,
      },
    }),
    { status: 200 },
  );
}

function accrualPlanListCalls(fetchMock: ReturnType<typeof vi.spyOn>) {
  return fetchMock.mock.calls.filter((call: unknown[]) => String(call[0]).includes("/accrual-plans"));
}

describe("AccrualPlansSection register", () => {
  it("requests open settlement and filter options by default", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(emptyListBody), { status: 200 }),
    );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);

    await waitFor(() => {
      const calls = accrualPlanListCalls(fetchMock);
      expect(calls.length).toBeGreaterThan(0);
      const url = String(calls[0][0]);
      expect(url).toContain("settlement_status=open");
      expect(url).toContain("include_filter_options=true");
    });
  });

  it("refetches with multiple party_ids when party filter selects more than one", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        listPlansResponse([], { party_ids: [1, 2], target_account_ids: [2, 4], bridge_account_ids: [1, 3] }),
      );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    await waitFor(() => expect(accrualPlanListCalls(fetchMock).length).toBe(1));

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Filter accrual plans by party" }));
    await user.click(screen.getByRole("checkbox", { name: "Acme Yard Maintenance" }));
    await user.click(screen.getByRole("checkbox", { name: "Beta Property Co" }));

    await waitFor(() => {
      const url = String(accrualPlanListCalls(fetchMock).at(-1)?.[0]);
      expect(url).toContain("party_ids=1");
      expect(url).toContain("party_ids=2");
    });
  });

  it("refetches when settlement filter changes", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(emptyListBody), { status: 200 }));

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    await waitFor(() => expect(accrualPlanListCalls(fetchMock).length).toBe(1));

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter accrual plans by settlement status"), "settled");

    await waitFor(() => {
      const calls = accrualPlanListCalls(fetchMock);
      expect(calls.length).toBeGreaterThan(1);
      expect(String(calls.at(-1)?.[0])).toContain("settlement_status=settled");
    });
  });

  it("refresh re-requests with current filters", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(emptyListBody), { status: 200 }));

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    await waitFor(() => expect(accrualPlanListCalls(fetchMock).length).toBe(1));
    fetchMock.mockClear();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Refresh list" }));

    await waitFor(() => {
      const calls = accrualPlanListCalls(fetchMock);
      expect(calls.length).toBe(1);
      expect(String(calls[0][0])).toContain("settlement_status=open");
    });
  });

  it("shows loading then empty state", async () => {
    let resolveFetch: (value: Response) => void = () => undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
    );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const register = screen.getByRole("table", { name: "Accrual plans register" });
    expect(within(register).getByText("Loading…")).toBeInTheDocument();

    resolveFetch(new Response(JSON.stringify(emptyListBody), { status: 200 }));
    expect(await within(register).findByText("No plans for this filter.")).toBeInTheDocument();
  });

  it("shows list error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("nope", { status: 500 }));

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);

    expect(await screen.findByText(/Request failed \(500\)/i)).toBeInTheDocument();
  });

  it("renders plan rows in the register table", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      listPlansResponse([
        {
          id: 5,
          name: "Alpha Rent",
          direction: "revenue",
          party_id: 1,
          target_account_id: 2,
          bridge_account_id: 1,
          frequency: "monthly_day",
          start_date: "2026-01-01",
          end_date: "2026-12-31",
          amount: "1200.00",
          summary_template: "{plan}",
          description_template: null,
          day_of_week: null,
          day_of_month: 1,
          month_of_year: null,
          business_day_adjust: false,
          created_at: "",
          updated_at: "",
        },
      ]),
    );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);

    const register = await screen.findByRole("table", { name: "Accrual plans register" });
    expect(within(register).getByText("Alpha Rent")).toBeInTheDocument();
    expect(within(register).getByText("Acme Yard Maintenance")).toBeInTheDocument();
    expect(within(register).getByText("$1,200.00")).toBeInTheDocument();
  });
});

describe("AccrualPlansSection create flow", () => {
  it("previews then creates a plan", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(listPlansResponse())
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
      )
      .mockResolvedValueOnce(
        listPlansResponse([
          {
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
          },
        ]),
      );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
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

    const register = await screen.findByRole("table", { name: "Accrual plans register" });
    await waitFor(() => expect(within(register).getByText("Rent Plan")).toBeInTheDocument());
  });

  it("shows a clear message when party is not selected on preview", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(listPlansResponse());
    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
    await user.click(screen.getByRole("button", { name: "Preview entries" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Select a party.");
    const previewCalls = fetchSpy.mock.calls.filter((c) => String(c[0]).includes("/preview"));
    expect(previewCalls).toHaveLength(0);
  });

  it("prevents preview when account types do not match direction", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(listPlansResponse());
    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Plan name"), "Bad Revenue Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
    await user.selectOptions(screen.getByLabelText("Plan direction"), "expense");
    await user.click(screen.getByRole("button", { name: "Preview entries" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Expense plans require an expense target account.",
    );
  });
});
