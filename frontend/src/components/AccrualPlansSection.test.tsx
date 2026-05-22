import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

async function openCreateDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /New accrual plan/i }));
  expect(screen.getByRole("heading", { name: "New accrual plan" })).toBeInTheDocument();
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

  it("does not show an inline create form on the main page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(listPlansResponse());

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    await waitFor(() => expect(screen.getByRole("table", { name: "Accrual plans register" })).toBeInTheDocument());

    expect(screen.queryByRole("heading", { name: "Create accrual plan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Preview entries/i })).not.toBeInTheDocument();
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
          has_settlement_allocations: false,
        },
      ]),
    );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);

    const register = await screen.findByRole("table", { name: "Accrual plans register" });
    expect(within(register).getByText("Alpha Rent")).toBeInTheDocument();
    expect(within(register).getByText("Acme Yard Maintenance")).toBeInTheDocument();
    expect(within(register).getByText("$1,200.00")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /View plan/i })).not.toBeInTheDocument();
  });
});

describe("AccrualPlansSection view modal", () => {
  const detailBody = {
    plan: {
      id: 7,
      name: "Settled Rent",
      direction: "revenue",
      party_id: 1,
      target_account_id: 2,
      bridge_account_id: 1,
      frequency: "monthly_day",
      start_date: "2026-01-01",
      end_date: "2026-03-31",
      amount: "300.00",
      summary_template: "{plan}",
      description_template: null,
      day_of_week: null,
      day_of_month: 1,
      month_of_year: null,
      business_day_adjust: false,
      created_at: "",
      updated_at: "",
    },
    summary: {
      total_original_accrued: "900.00",
      total_settled_to_date: "150.00",
      past_due: "300.00",
      not_yet_due: "200.00",
      unearned: "100.00",
    },
    obligations: [
      {
        id: 101,
        party_id: 1,
        accrual_plan_id: 7,
        source_entry_id: 1,
        source_entry_date: "2026-01-01",
        source_entry_summary: "Jan accrual",
        source_line_id: 1,
        obligation_type: "receivable",
        status: "open",
        original_amount: "300.00",
        open_amount: "300.00",
        created_at: "",
        updated_at: "",
      },
      {
        id: 102,
        party_id: 1,
        accrual_plan_id: 7,
        source_entry_id: 2,
        source_entry_date: "2026-02-01",
        source_entry_summary: "Feb accrual",
        source_line_id: 2,
        obligation_type: "receivable",
        status: "settled",
        original_amount: "300.00",
        open_amount: "0.00",
        created_at: "",
        updated_at: "",
      },
    ],
  };

  it("hides View when plan has no settlement allocations", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      listPlansResponse([
        {
          id: 3,
          name: "Fresh Plan",
          direction: "revenue",
          party_id: 1,
          target_account_id: 2,
          bridge_account_id: 1,
          frequency: "monthly_day",
          start_date: "2026-01-01",
          end_date: "2026-12-31",
          amount: "100.00",
          summary_template: "{plan}",
          description_template: null,
          day_of_week: null,
          day_of_month: 1,
          month_of_year: null,
          business_day_adjust: false,
          created_at: "",
          updated_at: "",
          has_settlement_allocations: false,
        },
      ]),
    );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    await waitFor(() => expect(screen.getByText("Fresh Plan")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /View plan/i })).not.toBeInTheDocument();
  });

  it("opens view modal with rollups and obligations from detail API", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        listPlansResponse([
          {
            id: 7,
            name: "Settled Rent",
            direction: "revenue",
            party_id: 1,
            target_account_id: 2,
            bridge_account_id: 1,
            frequency: "monthly_day",
            start_date: "2026-01-01",
            end_date: "2026-03-31",
            amount: "300.00",
            summary_template: "{plan}",
            description_template: null,
            day_of_week: null,
            day_of_month: 1,
            month_of_year: null,
            business_day_adjust: false,
            created_at: "",
            updated_at: "",
            has_settlement_allocations: true,
          },
        ]),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(detailBody), { status: 200 }));

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("Settled Rent")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "View plan Settled Rent" }));

    expect(await screen.findByRole("heading", { name: "Settled Rent" })).toBeInTheDocument();
    const rollups = screen.getByLabelText("Plan summary rollups");
    expect(within(rollups).getByText("Total original accrued")).toBeInTheDocument();
    expect(within(rollups).getByText("$900.00")).toBeInTheDocument();
    expect(within(rollups).getByText("Past due")).toBeInTheDocument();
    expect(within(rollups).getByText("$300.00")).toBeInTheDocument();
    expect(within(rollups).getByText("Unearned")).toBeInTheDocument();
    expect(within(rollups).getByText("$100.00")).toBeInTheDocument();

    const obligations = screen.getByRole("table", { name: "Plan obligations" });
    expect(within(obligations).getByText("2026-01-01")).toBeInTheDocument();
    expect(within(obligations).getByText("open")).toBeInTheDocument();
    expect(within(obligations).getByText("settled")).toBeInTheDocument();

    const detailCalls = vi.mocked(globalThis.fetch).mock.calls.filter((c) =>
      String(c[0]).match(/\/accrual-plans\/7$/),
    );
    expect(detailCalls).toHaveLength(1);
  });

  it("shows roll forward on frequency when business day adjust is enabled", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        listPlansResponse([
          {
            id: 7,
            name: "Settled Rent",
            direction: "revenue",
            party_id: 1,
            target_account_id: 2,
            bridge_account_id: 1,
            frequency: "monthly_day",
            start_date: "2026-01-01",
            end_date: "2026-03-31",
            amount: "300.00",
            summary_template: "{plan}",
            description_template: null,
            day_of_week: null,
            day_of_month: 1,
            month_of_year: null,
            business_day_adjust: true,
            created_at: "",
            updated_at: "",
            has_settlement_allocations: true,
          },
        ]),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...detailBody,
            plan: { ...detailBody.plan, business_day_adjust: true },
          }),
          { status: 200 },
        ),
      );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("Settled Rent")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "View plan Settled Rent" }));

    expect(await screen.findByText("monthly (day 1) (roll forward)")).toBeInTheDocument();
    expect(screen.queryByText(/Roll weekends/i)).not.toBeInTheDocument();
  });
});

describe("AccrualPlansSection create flow", () => {
  it("previews then creates a plan via the create modal", async () => {
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
    await waitFor(() => expect(screen.getByRole("table", { name: "Accrual plans register" })).toBeInTheDocument());

    await openCreateDialog(user);
    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
    await user.clear(screen.getByLabelText("Plan amount"));
    await user.type(screen.getByLabelText("Plan amount"), "100.00");
    await user.click(screen.getByRole("button", { name: /Preview entries/i }));

    expect(await screen.findByRole("heading", { name: "Preview accrual entries" })).toBeInTheDocument();
    const previewTable = screen.getByRole("table", { name: "Accrual preview" });
    expect(within(previewTable).getByText("Plan 2026-01")).toBeInTheDocument();
    expect(within(previewTable).getByText("Acme Yard Maintenance")).toBeInTheDocument();
    expect(within(previewTable).getByText("Accounts Receivable")).toBeInTheDocument();
    expect(within(previewTable).getByText("Rent Revenue")).toBeInTheDocument();
    expect(within(previewTable).getByText("100.00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Create plan/i }));

    const register = await screen.findByRole("table", { name: "Accrual plans register" });
    await waitFor(() => expect(within(register).getByText("Rent Plan")).toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "New accrual plan" })).not.toBeInTheDocument();
  });

  it("returns to the edit form when preview cancel is used", async () => {
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
      );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("table", { name: "Accrual plans register" })).toBeInTheDocument());

    await openCreateDialog(user);
    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
    await user.click(screen.getByRole("button", { name: /Preview entries/i }));
    expect(await screen.findByRole("heading", { name: "Preview accrual entries" })).toBeInTheDocument();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByText("Cancel"));

    expect(screen.getByRole("heading", { name: "New accrual plan" })).toBeInTheDocument();
    expect(screen.getByLabelText("Plan name")).toHaveValue("Rent Plan");
    expect(screen.queryByRole("table", { name: "Accrual preview" })).not.toBeInTheDocument();
  });

  it("shows a clear message when party is not selected on preview", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(listPlansResponse());
    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("table", { name: "Accrual plans register" })).toBeInTheDocument());

    await openCreateDialog(user);
    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
    await user.click(screen.getByRole("button", { name: /Preview entries/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Select a party.");
    const previewCalls = fetchSpy.mock.calls.filter((c) => String(c[0]).includes("/preview"));
    expect(previewCalls).toHaveLength(0);
  });

  it("prevents preview when account types do not match direction", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(listPlansResponse());
    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("table", { name: "Accrual plans register" })).toBeInTheDocument());

    await openCreateDialog(user);
    await user.type(screen.getByLabelText("Plan name"), "Bad Revenue Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
    await user.selectOptions(screen.getByLabelText("Plan direction"), "expense");
    await user.click(screen.getByRole("button", { name: /Preview entries/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Expense plans require an expense target account.",
    );
  });

  it("closes the create dialog when Escape is pressed on the form", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(listPlansResponse());
    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("table", { name: "Accrual plans register" })).toBeInTheDocument());

    await openCreateDialog(user);
    await user.type(screen.getByLabelText("Plan name"), "Discard me");
    fireEvent.keyDown(document, { key: "Escape", code: "Escape", bubbles: true });

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "New accrual plan" })).not.toBeInTheDocument();
    });
  });

  it("closes the create dialog when Escape is pressed on preview", async () => {
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
      );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("table", { name: "Accrual plans register" })).toBeInTheDocument());

    await openCreateDialog(user);
    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
    await user.click(screen.getByRole("button", { name: /Preview entries/i }));
    expect(await screen.findByRole("heading", { name: "Preview accrual entries" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape", code: "Escape", bubbles: true });

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Preview accrual entries" })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "New accrual plan" })).not.toBeInTheDocument();
    });
  });

  it("returns to the create form when Ctrl+Shift+D is pressed on preview", async () => {
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
      );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("table", { name: "Accrual plans register" })).toBeInTheDocument());

    await openCreateDialog(user);
    await user.type(screen.getByLabelText("Plan name"), "Rent Plan");
    await user.selectOptions(screen.getByLabelText("Plan party"), "1");
    await user.selectOptions(screen.getByLabelText("Plan target account"), "2");
    await user.selectOptions(screen.getByLabelText("Plan bridge account"), "1");
    await user.click(screen.getByRole("button", { name: /Preview entries/i }));
    expect(await screen.findByRole("heading", { name: "Preview accrual entries" })).toBeInTheDocument();

    fireEvent.keyDown(document, {
      key: "d",
      code: "KeyD",
      ctrlKey: true,
      shiftKey: true,
      bubbles: true,
    });

    expect(screen.getByRole("heading", { name: "New accrual plan" })).toBeInTheDocument();
    expect(screen.getByLabelText("Plan name")).toHaveValue("Rent Plan");
    expect(screen.queryByRole("table", { name: "Accrual preview" })).not.toBeInTheDocument();
  });
});

const unsettledPlanRow = {
  id: 3,
  name: "Fresh Plan",
  direction: "revenue" as const,
  party_id: 1,
  target_account_id: 2,
  bridge_account_id: 1,
  frequency: "monthly_day" as const,
  start_date: "2026-01-01",
  end_date: "2026-12-31",
  amount: "100.00",
  summary_template: "{plan}",
  description_template: null,
  day_of_week: null,
  day_of_month: 1,
  month_of_year: null,
  business_day_adjust: false,
  created_at: "",
  updated_at: "",
  has_settlement_allocations: false,
};

const previewResponse = new Response(
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
);

describe("AccrualPlansSection edit and cancel", () => {
  it("shows Edit and Cancel for unsettled plans and hides View", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(listPlansResponse([unsettledPlanRow]));

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    await waitFor(() => expect(screen.getByText("Fresh Plan")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Edit plan Fresh Plan" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel plan Fresh Plan" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /View plan/i })).not.toBeInTheDocument();
  });

  it("hides Edit and Cancel when plan has settlement allocations", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      listPlansResponse([
        {
          ...unsettledPlanRow,
          id: 7,
          name: "Settled Rent",
          has_settlement_allocations: true,
        },
      ]),
    );

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    await waitFor(() => expect(screen.getByText("Settled Rent")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Edit plan/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Cancel plan/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View plan Settled Rent" })).toBeInTheDocument();
  });

  it("previews then saves an edit via PATCH and refreshes the list", async () => {
    const updatedPlan = { ...unsettledPlanRow, amount: "150.00" };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(listPlansResponse([unsettledPlanRow]))
      .mockResolvedValueOnce(previewResponse)
      .mockResolvedValueOnce(new Response(JSON.stringify(updatedPlan), { status: 200 }))
      .mockResolvedValueOnce(listPlansResponse([updatedPlan]));

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("Fresh Plan")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Edit plan Fresh Plan" }));
    expect(await screen.findByRole("heading", { name: "Edit accrual plan" })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Plan amount"));
    await user.type(screen.getByLabelText("Plan amount"), "150.00");
    await user.click(screen.getByRole("button", { name: /Preview entries/i }));
    expect(await screen.findByRole("heading", { name: "Preview accrual entries" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Save plan/i }));

    const register = await screen.findByRole("table", { name: "Accrual plans register" });
    await waitFor(() => expect(within(register).getByText("Fresh Plan")).toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "Edit accrual plan" })).not.toBeInTheDocument();

    const patchCalls = vi.mocked(globalThis.fetch).mock.calls.filter(
      (c) => String(c[0]).includes("/accrual-plans/3") && (c[1] as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patchCalls).toHaveLength(1);
  });

  it("removes the plan from the list after cancel is confirmed", async () => {
    vi.spyOn(globalThis, "confirm").mockReturnValue(true);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(listPlansResponse([unsettledPlanRow]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(listPlansResponse([]));

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("Fresh Plan")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Cancel plan Fresh Plan" }));

    await waitFor(() => {
      expect(screen.getByText("No plans for this filter.")).toBeInTheDocument();
    });
    const deleteCalls = vi.mocked(globalThis.fetch).mock.calls.filter(
      (c) => String(c[0]).includes("/accrual-plans/3") && (c[1] as RequestInit | undefined)?.method === "DELETE",
    );
    expect(deleteCalls).toHaveLength(1);
  });

  it("does not DELETE when cancel confirmation is declined", async () => {
    vi.spyOn(globalThis, "confirm").mockReturnValue(false);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(listPlansResponse([unsettledPlanRow]));

    render(<AccrualPlansSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("Fresh Plan")).toBeInTheDocument());
    fetchMock.mockClear();

    await user.click(screen.getByRole("button", { name: "Cancel plan Fresh Plan" }));

    const deleteCalls = fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes("/accrual-plans/3") && (c[1] as RequestInit | undefined)?.method === "DELETE",
    );
    expect(deleteCalls).toHaveLength(0);
    expect(screen.getByText("Fresh Plan")).toBeInTheDocument();
  });
});
