import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import type { Party } from "../api/parties";
import { ChequesSection } from "./ChequesSection";

afterEach(() => {
  vi.restoreAllMocks();
});

const accounts: Account[] = [
  {
    id: 1,
    name: "Chequing",
    type: "asset",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
  {
    id: 2,
    name: "Rent",
    type: "expense",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
];

const parties: Party[] = [];

interface RouteMocks {
  cheques?: unknown;
  filterOptions?: {
    parties: Array<{ id: number | null; name: string }>;
    credit_accounts: Array<{ id: number; name: string }>;
    debit_accounts: Array<{ id: number; name: string }>;
  };
  settings?: Partial<{
    accounts_receivable_account_id: number | null;
    accounts_payable_account_id: number | null;
    unearned_revenue_account_id: number | null;
    unallocated_debits_account_id: number | null;
    unallocated_credits_account_id: number | null;
    default_cheque_credit_account_id: number | null;
    default_cheque_debit_account_id: number | null;
    max_attachment_upload_bytes: number;
    max_cheque_series_count: number;
    updated_at: string;
  }>;
}

function defaultSettings(overrides: RouteMocks["settings"] = {}) {
  return {
    accounts_receivable_account_id: null,
    accounts_payable_account_id: null,
    unearned_revenue_account_id: null,
    unallocated_debits_account_id: null,
    unallocated_credits_account_id: null,
    default_cheque_credit_account_id: null,
    default_cheque_debit_account_id: null,
    max_attachment_upload_bytes: 5_242_880,
    max_cheque_series_count: 60,
    updated_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

function defaultFilterOptions() {
  return {
    parties: [
      { id: null, name: "(no party)" },
      { id: 10, name: "Bill Smith" },
    ],
    credit_accounts: [{ id: 1, name: "Chequing" }],
    debit_accounts: [{ id: 2, name: "Rent" }],
  };
}

function filterOptionsResponse() {
  return new Response(JSON.stringify(defaultFilterOptions()), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function chequeListCalls(fetchMock: ReturnType<typeof vi.spyOn>) {
  return fetchMock.mock.calls.filter((call: unknown[]) => {
    const url = String(call[0]);
    return url.includes("/cheques") && !url.includes("/filter-options");
  });
}

function installFetchMock(routes: RouteMocks = {}) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/ledger-settings")) {
        return new Response(JSON.stringify(defaultSettings(routes.settings)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques/filter-options")) {
        return new Response(JSON.stringify(routes.filterOptions ?? defaultFilterOptions()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify({ cheques: routes.cheques ?? [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("not found", { status: 404 });
    });
}

describe("ChequesSection", () => {
  it("requests cheques with status=open by default", async () => {
    const fetchMock = installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => {
      const chequeCalls = chequeListCalls(fetchMock);
      expect(chequeCalls.length).toBeGreaterThan(0);
      expect(String(chequeCalls[0][0])).toContain("status=open");
    });
  });

  it("requests party_ids=null when (no party) is selected", async () => {
    const fetchMock = installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => expect(chequeListCalls(fetchMock).length).toBeGreaterThan(0));

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Filter cheques by party" }));
    await user.click(screen.getByRole("checkbox", { name: "(no party)" }));

    await waitFor(() => {
      const url = String(chequeListCalls(fetchMock).at(-1)?.[0]);
      expect(url).toContain("party_ids=null");
      expect(url).not.toContain("include_no_party");
    });
  });

  it("requests numeric party_ids and party_ids=null when both are selected", async () => {
    const fetchMock = installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => expect(chequeListCalls(fetchMock).length).toBeGreaterThan(0));

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Filter cheques by party" }));
    await user.click(screen.getByRole("checkbox", { name: "Bill Smith" }));
    await user.click(screen.getByRole("checkbox", { name: "(no party)" }));

    await waitFor(() => {
      const url = String(chequeListCalls(fetchMock).at(-1)?.[0]);
      expect(url).toContain("party_ids=10");
      expect(url).toContain("party_ids=null");
    });
  });

  it("requests summary filter in the list URL", async () => {
    const fetchMock = installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => expect(chequeListCalls(fetchMock).length).toBeGreaterThan(0));

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Filter cheques by summary"), "rent");

    await waitFor(() => {
      const url = String(chequeListCalls(fetchMock).at(-1)?.[0]);
      expect(url).toContain("summary=rent");
    });
  });

  it("refresh re-requests with current filters", async () => {
    const fetchMock = installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => expect(chequeListCalls(fetchMock).length).toBeGreaterThan(0));

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter cheques by status"), "cleared");
    await waitFor(() => {
      expect(String(chequeListCalls(fetchMock).at(-1)?.[0])).toContain("status=cleared");
    });

    fetchMock.mockClear();
    await user.click(screen.getByRole("button", { name: "Refresh list" }));

    await waitFor(() => {
      const calls = chequeListCalls(fetchMock);
      expect(calls.length).toBe(1);
      expect(String(calls[0][0])).toContain("status=cleared");
    });
  });

  it("renders Cleared column with date or em dash", async () => {
    installFetchMock({
      cheques: [
        {
          id: 1,
          credit_account_id: 1,
          debit_account_id: 2,
          summary: "Open one",
          cheque_number: 1,
          issue_date: "2026-05-01",
          cleared_date: null,
          amount: "10.00",
          party_id: null,
          status: "open",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
        {
          id: 2,
          credit_account_id: 1,
          debit_account_id: 2,
          summary: "Cleared one",
          cheque_number: 2,
          issue_date: "2026-05-02",
          cleared_date: "2026-05-03",
          amount: "20.00",
          party_id: null,
          status: "cleared",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const table = await screen.findByRole("table");
    const openRow = within(table).getByRole("row", { name: /Open one/i });
    const clearedRow = within(table).getByRole("row", { name: /Cleared one/i });
    expect(within(openRow).getAllByRole("cell")[4]).toHaveTextContent("—");
    expect(within(clearedRow).getAllByRole("cell")[4]).toHaveTextContent("2026-05-03");
  });

  it("requests status=all when filter is All", async () => {
    const fetchMock = installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    fetchMock.mockClear();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter cheques by status"), "all");

    await waitFor(() => {
      const chequeCalls = chequeListCalls(fetchMock);
      expect(chequeCalls.length).toBeGreaterThan(0);
      expect(String(chequeCalls[0][0])).toContain("status=all");
    });
  });

  it("does not offer Void on cleared cheque rows", async () => {
    installFetchMock({
      cheques: [
        {
          id: 9,
          credit_account_id: 1,
          debit_account_id: 2,
          summary: "Cleared one",
          cheque_number: 3,
          issue_date: "2026-05-02",
          cleared_date: "2026-05-03",
          amount: "40.00",
          party_id: null,
          status: "cleared",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const table = await screen.findByRole("table");
    const row = within(table).getByRole("row", { name: /Cleared one/i });
    expect(within(row).queryByRole("button", { name: /Void cheque/i })).not.toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "View cheque #3" })).toBeInTheDocument();
  });

  it("shows View and Re-open for void cheque rows but not Edit", async () => {
    installFetchMock({
      cheques: [
        {
          id: 8,
          credit_account_id: 1,
          debit_account_id: 2,
          summary: "Voided",
          cheque_number: 2,
          issue_date: "2026-05-02",
          cleared_date: null,
          amount: "12.00",
          party_id: null,
          status: "void",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const table = await screen.findByRole("table");
    const row = within(table).getByRole("row", { name: /Voided/i });
    expect(within(row).getByRole("button", { name: "View cheque #2" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Re-open cheque #2" })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Edit cheque #2" })).not.toBeInTheDocument();
  });

  it("opens void cheque in read-only view dialog via Eye", async () => {
    installFetchMock({
      cheques: [
        {
          id: 8,
          credit_account_id: 1,
          debit_account_id: 2,
          summary: "Voided",
          cheque_number: 2,
          issue_date: "2026-05-02",
          cleared_date: null,
          amount: "12.00",
          party_id: null,
          status: "void",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByRole("button", { name: "View cheque #2" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "View cheque #2" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Save changes/i })).not.toBeInTheDocument();
  });

  it("row click highlights only and does not open edit dialog", async () => {
    installFetchMock({
      cheques: [
        {
          id: 7,
          credit_account_id: 1,
          debit_account_id: 2,
          summary: "Open one",
          cheque_number: 1,
          issue_date: "2026-05-02",
          cleared_date: null,
          amount: "25.00",
          party_id: null,
          status: "open",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByText("Open one"));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens edit via Pencil and has no status dropdown on the edit form", async () => {
    installFetchMock({
      cheques: [
        {
          id: 7,
          credit_account_id: 1,
          debit_account_id: 2,
          summary: "Open one",
          cheque_number: 1,
          issue_date: "2026-05-02",
          cleared_date: null,
          amount: "25.00",
          party_id: null,
          status: "open",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByRole("button", { name: "Edit cheque #1" }));

    const dialog = await screen.findByRole("dialog");
    const selects = within(dialog).getAllByRole("combobox");
    const statusField = selects.find((el) => el.getAttribute("aria-label") === "Cheque status");
    expect(statusField).toBeUndefined();
  });

  it("opens cleared cheque in read-only view dialog via Eye", async () => {
    installFetchMock({
      cheques: [
        {
          id: 9,
          credit_account_id: 1,
          debit_account_id: 2,
          summary: "Cleared one",
          cheque_number: 3,
          issue_date: "2026-05-02",
          cleared_date: "2026-05-03",
          amount: "40.00",
          party_id: null,
          status: "cleared",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByRole("button", { name: "View cheque #3" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "View cheque #3" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Save changes/i })).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText(/^Summary/i)).toBeDisabled();
  });
});

describe("ChequesSection #105 — picker eligibility and last-used defaults", () => {
  const richAccounts: Account[] = [
    {
      id: 1,
      name: "Chequing",
      type: "asset",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
    {
      id: 2,
      name: "Savings",
      type: "asset",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
    {
      id: 3,
      name: "Rent",
      type: "expense",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
    {
      id: 4,
      name: "Unallocated Debits",
      type: "suspense",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
    {
      id: 5,
      name: "Old Bank",
      type: "asset",
      is_active: false,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ];

  it("credit picker lists active asset accounts only on a new cheque", async () => {
    installFetchMock();

    render(<ChequesSection accounts={richAccounts} parties={parties} />);
    await screen.findByRole("table");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /New cheque/i }));

    const creditSelect = await within(await screen.findByRole("dialog")).findByLabelText(
      /Credit account \(cheque\)/i,
    );
    const optionNames = within(creditSelect)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).text);
    // Eligible asset accounts present, with parenthesised type tag.
    expect(optionNames).toEqual(
      expect.arrayContaining(["Chequing (asset)", "Savings (asset)"]),
    );
    // Inactive asset, expense, suspense excluded.
    expect(optionNames).not.toEqual(expect.arrayContaining(["Old Bank (asset, inactive)"]));
    expect(optionNames.filter((n) => n.startsWith("Rent"))).toEqual([]);
    expect(optionNames.filter((n) => n.startsWith("Unallocated Debits"))).toEqual([]);
  });

  it("debit picker lists active non-suspense accounts only on a new cheque", async () => {
    installFetchMock();

    render(<ChequesSection accounts={richAccounts} parties={parties} />);
    await screen.findByRole("table");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /New cheque/i }));

    const debitSelect = await screen.findByLabelText(/^Debit account/i);
    const optionNames = within(debitSelect)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).text);
    expect(optionNames).toEqual(
      expect.arrayContaining(["Chequing (asset)", "Savings (asset)", "Rent (expense)"]),
    );
    // Suspense excluded; inactive asset excluded.
    expect(optionNames.filter((n) => n.startsWith("Unallocated Debits"))).toEqual([]);
    expect(optionNames.filter((n) => n.startsWith("Old Bank"))).toEqual([]);
  });

  it("pre-fills new cheque from eligible default accounts", async () => {
    installFetchMock({
      settings: {
        default_cheque_credit_account_id: 2,
        default_cheque_debit_account_id: 3,
      },
    });

    render(<ChequesSection accounts={richAccounts} parties={parties} />);
    await screen.findByRole("table");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /New cheque/i }));

    const creditSelect = (await within(await screen.findByRole("dialog")).findByLabelText(
      /Credit account \(cheque\)/i,
    )) as HTMLSelectElement;
    const debitSelect = (await screen.findByLabelText(/^Debit account/i)) as HTMLSelectElement;
    expect(creditSelect.value).toBe("2");
    expect(debitSelect.value).toBe("3");
  });

  it("leaves new-cheque sides unset when the stored default is no longer eligible", async () => {
    installFetchMock({
      settings: {
        default_cheque_credit_account_id: 5, // Old Bank — asset but inactive.
        default_cheque_debit_account_id: 4, // Suspense — never eligible as debit.
      },
    });

    render(<ChequesSection accounts={richAccounts} parties={parties} />);
    await screen.findByRole("table");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /New cheque/i }));

    const creditSelect = (await within(await screen.findByRole("dialog")).findByLabelText(
      /Credit account \(cheque\)/i,
    )) as HTMLSelectElement;
    const debitSelect = (await screen.findByLabelText(/^Debit account/i)) as HTMLSelectElement;
    expect(creditSelect.value).toBe("");
    expect(debitSelect.value).toBe("");
  });

  it("editing a cheque keeps a now-inactive credit account visible and selected", async () => {
    installFetchMock({
      cheques: [
        {
          id: 11,
          credit_account_id: 5, // Old Bank — inactive.
          debit_account_id: 3, // Rent — still active expense.
          summary: "Legacy cheque",
          cheque_number: 99,
          issue_date: "2026-05-02",
          cleared_date: null,
          amount: "75.00",
          party_id: null,
          status: "open",
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    render(<ChequesSection accounts={richAccounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByRole("button", { name: "Edit cheque #99" }));

    const dialog = await screen.findByRole("dialog");
    const creditSelect = (await within(dialog).findByLabelText(/Credit account \(cheque\)/i)) as HTMLSelectElement;
    expect(creditSelect.value).toBe("5");
    const optionNames = within(creditSelect)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).text);
    // Inactive Old Bank rendered with annotation alongside eligible options.
    expect(optionNames).toEqual(expect.arrayContaining(["Old Bank (asset, inactive)"]));
    expect(optionNames).toEqual(expect.arrayContaining(["Chequing (asset)", "Savings (asset)"]));
  });
});

describe("ChequesSection #141 — cheque series", () => {
  it("previews series and blocks create when a cheque number conflicts", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ledger-settings")) {
        return new Response(JSON.stringify(defaultSettings()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques/filter-options")) {
        return filterOptionsResponse();
      }
      if (url.includes("/cheques/series/preview") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            rows: [
              {
                cheque_number: 1001,
                issue_date: "2025-11-01",
                amount: "900.00",
                number_conflict: false,
              },
              {
                cheque_number: 1002,
                issue_date: "2025-12-01",
                amount: "900.00",
                number_conflict: true,
              },
            ],
            series_count: 2,
            max_allowed: 60,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("/cheques/series") && init?.method === "POST") {
        return new Response(JSON.stringify([]), { status: 201 });
      }
      return new Response(JSON.stringify({ cheques: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /New cheque/i }));
    const createDialog = await screen.findByRole("dialog");
    await user.click(within(createDialog).getByRole("checkbox", { name: /Create as series/i }));
    await user.selectOptions(within(createDialog).getByLabelText(/Credit account \(cheque\)/i), "1");
    await user.selectOptions(within(createDialog).getByLabelText(/^Debit account/i), "2");
    await user.type(within(createDialog).getByLabelText(/^Summary/i), "Snow");
    await user.type(within(createDialog).getByLabelText(/Starting cheque number/i), "1001");
    fireEvent.change(within(createDialog).getByLabelText(/First issue date/i), {
      target: { value: "2025-11-01" },
    });
    await user.type(within(createDialog).getByLabelText(/^Amount/i), "900");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => {
      expect(screen.getByText("Open cheque number already in use on this credit account")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /create series/i })).toBeDisabled();

    fetchMock.mockRestore();
  });

  it("creates a series after a clean preview", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ledger-settings")) {
        return new Response(JSON.stringify(defaultSettings()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques/filter-options")) {
        return filterOptionsResponse();
      }
      if (url.includes("/cheques/series/preview")) {
        return new Response(
          JSON.stringify({
            rows: [
              {
                cheque_number: 10,
                issue_date: "2026-01-01",
                amount: "50.00",
                number_conflict: false,
              },
            ],
            series_count: 1,
            max_allowed: 60,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("/cheques/series") && init?.method === "POST") {
        return new Response(
          JSON.stringify([
            {
              id: 50,
              credit_account_id: 1,
              debit_account_id: 2,
              summary: "Series",
              cheque_number: 10,
              issue_date: "2026-01-01",
              cleared_date: null,
              amount: "50.00",
              party_id: null,
              status: "open",
              created_at: "2026-04-01T00:00:00Z",
              updated_at: "2026-04-01T00:00:00Z",
            },
          ]),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ cheques: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /New cheque/i }));
    const createDialog = await screen.findByRole("dialog");
    await user.click(within(createDialog).getByRole("checkbox", { name: /Create as series/i }));
    await user.selectOptions(within(createDialog).getByLabelText(/Credit account \(cheque\)/i), "1");
    await user.selectOptions(within(createDialog).getByLabelText(/^Debit account/i), "2");
    await user.type(within(createDialog).getByLabelText(/^Summary/i), "Series");
    await user.type(within(createDialog).getByLabelText(/Starting cheque number/i), "10");
    fireEvent.change(within(createDialog).getByLabelText(/First issue date/i), {
      target: { value: "2026-01-01" },
    });
    await user.type(within(createDialog).getByLabelText(/^Amount/i), "50");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /create series/i })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: /create series/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/cheques/series") && c[1]?.method === "POST")).toBe(
        true,
      );
    });

    fetchMock.mockRestore();
  });
});

const openCheque = {
  id: 7,
  credit_account_id: 1,
  debit_account_id: 2,
  summary: "Open one",
  cheque_number: 1,
  issue_date: "2026-05-02",
  cleared_date: null,
  amount: "25.00",
  party_id: null,
  status: "open" as const,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

describe("ChequesSection #132 — keyboard shortcuts", () => {
  it("saves the edit form when Ctrl+S is pressed in the edit dialog", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ledger-settings")) {
        return new Response(JSON.stringify(defaultSettings()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques/filter-options")) {
        return filterOptionsResponse();
      }
      if (url.includes("/cheques/7") && init?.method === "PATCH") {
        return new Response(
          JSON.stringify({ ...openCheque, summary: "Updated via keyboard" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ cheques: [openCheque] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByRole("button", { name: "Edit cheque #1" }));
    const dialog = await screen.findByRole("dialog");
    const summaryInput = within(dialog).getByLabelText(/^Summary/i);
    await user.clear(summaryInput);
    await user.type(summaryInput, "Updated via keyboard");
    summaryInput.focus();
    fireEvent.keyDown(summaryInput, { key: "s", code: "KeyS", ctrlKey: true, bubbles: true });

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/cheques/7") && c[1]?.method === "PATCH")).toBe(
        true,
      );
    });

    fetchMock.mockRestore();
  });

  it("closes the edit dialog after a successful save", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ledger-settings")) {
        return new Response(JSON.stringify(defaultSettings()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques/filter-options")) {
        return filterOptionsResponse();
      }
      if (url.includes("/cheques/7") && init?.method === "PATCH") {
        return new Response(
          JSON.stringify({ ...openCheque, summary: "Saved in modal" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ cheques: [openCheque] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByRole("button", { name: "Edit cheque #1" }));
    const dialog = await screen.findByRole("dialog");
    const summaryInput = within(dialog).getByLabelText(/^Summary/i);
    await user.clear(summaryInput);
    await user.type(summaryInput, "Saved in modal");
    await user.click(within(dialog).getByRole("button", { name: /Save changes/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    fetchMock.mockRestore();
  });

  it("discards edit changes silently when Escape is pressed", async () => {
    installFetchMock({
      cheques: [openCheque],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByRole("button", { name: "Edit cheque #1" }));
    const dialog = await screen.findByRole("dialog");
    const summaryInput = within(dialog).getByLabelText(/^Summary/i);
    await user.clear(summaryInput);
    await user.type(summaryInput, "Draft change");
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    await user.click(within(table).getByRole("button", { name: "Edit cheque #1" }));
    const reopened = await screen.findByRole("dialog");
    expect(within(reopened).getByLabelText(/^Summary/i)).toHaveValue("Open one");
  });

  it("reverts edit form fields when Ctrl+Shift+D is pressed in the edit dialog", async () => {
    installFetchMock({
      cheques: [openCheque],
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByRole("button", { name: "Edit cheque #1" }));
    const dialog = await screen.findByRole("dialog");
    const summaryInput = within(dialog).getByLabelText(/^Summary/i);
    await user.clear(summaryInput);
    await user.type(summaryInput, "Changed");
    fireEvent.keyDown(document, { key: "d", ctrlKey: true, shiftKey: true });

    expect(within(dialog).getByLabelText(/^Summary/i)).toHaveValue("Open one");
  });

  it("creates a single cheque when Ctrl+S is pressed in the create dialog", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ledger-settings")) {
        return new Response(JSON.stringify(defaultSettings()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques/filter-options")) {
        return filterOptionsResponse();
      }
      if (url.includes("/cheques") && !url.includes("/series") && init?.method === "POST") {
        return new Response(
          JSON.stringify({ ...openCheque, id: 99, summary: "Keyboard create" }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ cheques: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /New cheque/i }));
    const createDialog = await screen.findByRole("dialog");
    await user.selectOptions(within(createDialog).getByLabelText(/Credit account \(cheque\)/i), "1");
    await user.selectOptions(within(createDialog).getByLabelText(/^Debit account/i), "2");
    await user.type(within(createDialog).getByLabelText(/^Summary/i), "Keyboard create");
    await user.type(within(createDialog).getByLabelText(/^Cheque number/i), "42");
    fireEvent.change(within(createDialog).getByLabelText(/^Issue date/i), { target: { value: "2026-05-10" } });
    const amountInput = within(createDialog).getByLabelText(/^Amount/i);
    await user.type(amountInput, "100");
    amountInput.focus();
    fireEvent.keyDown(amountInput, { key: "s", code: "KeyS", ctrlKey: true, bubbles: true });

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (c) => String(c[0]).includes("/cheques") && !String(c[0]).includes("/series") && c[1]?.method === "POST",
        ),
      ).toBe(true);
    });
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "New cheque" })).not.toBeInTheDocument();
    });

    fetchMock.mockRestore();
  });

  it("shows series preview when Ctrl+S is pressed on the series form view", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ledger-settings")) {
        return new Response(JSON.stringify(defaultSettings()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques/filter-options")) {
        return filterOptionsResponse();
      }
      if (url.includes("/cheques/series/preview") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            rows: [
              {
                cheque_number: 10,
                issue_date: "2026-01-01",
                amount: "50.00",
                number_conflict: false,
              },
            ],
            series_count: 1,
            max_allowed: 60,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ cheques: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /New cheque/i }));
    const createDialog = await screen.findByRole("dialog");
    await user.click(within(createDialog).getByRole("checkbox", { name: /Create as series/i }));
    await user.selectOptions(within(createDialog).getByLabelText(/Credit account \(cheque\)/i), "1");
    await user.selectOptions(within(createDialog).getByLabelText(/^Debit account/i), "2");
    await user.type(within(createDialog).getByLabelText(/^Summary/i), "Series");
    await user.type(within(createDialog).getByLabelText(/Starting cheque number/i), "10");
    fireEvent.change(within(createDialog).getByLabelText(/First issue date/i), { target: { value: "2026-01-01" } });
    const amountInput = within(createDialog).getByLabelText(/^Amount/i);
    await user.type(amountInput, "50");
    amountInput.focus();
    fireEvent.keyDown(amountInput, { key: "s", code: "KeyS", ctrlKey: true, bubbles: true });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Preview cheque series" })).toBeInTheDocument();
    });
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/cheques/series/preview"))).toBe(true);

    fetchMock.mockRestore();
  });

  it("creates a series when Ctrl+S is pressed on the preview view", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ledger-settings")) {
        return new Response(JSON.stringify(defaultSettings()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/cheques/filter-options")) {
        return filterOptionsResponse();
      }
      if (url.includes("/cheques/series/preview")) {
        return new Response(
          JSON.stringify({
            rows: [
              {
                cheque_number: 10,
                issue_date: "2026-01-01",
                amount: "50.00",
                number_conflict: false,
              },
            ],
            series_count: 1,
            max_allowed: 60,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("/cheques/series") && init?.method === "POST") {
        return new Response(JSON.stringify([{ ...openCheque, id: 50 }]), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ cheques: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /New cheque/i }));
    const createDialog = await screen.findByRole("dialog");
    await user.click(within(createDialog).getByRole("checkbox", { name: /Create as series/i }));
    await user.selectOptions(within(createDialog).getByLabelText(/Credit account \(cheque\)/i), "1");
    await user.selectOptions(within(createDialog).getByLabelText(/^Debit account/i), "2");
    await user.type(within(createDialog).getByLabelText(/^Summary/i), "Series");
    await user.type(within(createDialog).getByLabelText(/Starting cheque number/i), "10");
    fireEvent.change(within(createDialog).getByLabelText(/First issue date/i), { target: { value: "2026-01-01" } });
    await user.type(within(createDialog).getByLabelText(/^Amount/i), "50");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /create series \(ctrl\+s\)/i })).toBeEnabled();
    });
    // Preview unmounts the Preview button; focus often lands on body, not the submit control.
    document.body.focus();
    fireEvent.keyDown(document.body, { key: "s", code: "KeyS", ctrlKey: true, bubbles: true });

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/cheques/series") && c[1]?.method === "POST")).toBe(
        true,
      );
    });

    fetchMock.mockRestore();
  });

  it("closes the create dialog when Escape is pressed", async () => {
    installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /New cheque/i }));
    const createDialog = await screen.findByRole("dialog");
    await user.type(within(createDialog).getByLabelText(/^Summary/i), "Draft summary");
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "New cheque" })).not.toBeInTheDocument();
    });
  });

  it("reverts create form fields in place when Ctrl+Shift+D is pressed on the form step", async () => {
    installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /New cheque/i }));
    const createDialog = await screen.findByRole("dialog");
    await user.type(within(createDialog).getByLabelText(/^Summary/i), "Changed");
    fireEvent.keyDown(document, { key: "d", ctrlKey: true, shiftKey: true });

    expect(screen.getByRole("heading", { name: "New cheque" })).toBeInTheDocument();
    expect(within(createDialog).getByLabelText(/^Summary/i)).toHaveValue("");
  });
});
