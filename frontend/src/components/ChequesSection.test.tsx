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
      return new Response(JSON.stringify(routes.cheques ?? []), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
}

describe("ChequesSection", () => {
  it("requests cheques with status=open by default", async () => {
    const fetchMock = installFetchMock();

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => {
      const chequeCalls = fetchMock.mock.calls.filter(
        (call: unknown[]) => String(call[0]).includes("/cheques"),
      );
      expect(chequeCalls.length).toBeGreaterThan(0);
      expect(String(chequeCalls[0][0])).toContain("status=open");
    });
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
      const chequeCalls = fetchMock.mock.calls.filter(
        (call: unknown[]) => String(call[0]).includes("/cheques"),
      );
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
    expect(within(row).queryByRole("button", { name: "Void" })).not.toBeInTheDocument();
  });

  it("shows Re-open for void cheque rows", async () => {
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
    expect(within(table).getByRole("button", { name: "Re-open" })).toBeInTheDocument();
  });

  it("has no status dropdown on the edit form", async () => {
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

    const selects = screen.getAllByRole("combobox");
    const statusField = selects.find((el) => el.getAttribute("aria-label") === "Cheque status");
    expect(statusField).toBeUndefined();
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
    await user.click(screen.getByRole("button", { name: "New cheque" }));

    const creditSelect = await screen.findByLabelText(/Credit account/i);
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
    await user.click(screen.getByRole("button", { name: "New cheque" }));

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
    await user.click(screen.getByRole("button", { name: "New cheque" }));

    const creditSelect = (await screen.findByLabelText(/Credit account/i)) as HTMLSelectElement;
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
    await user.click(screen.getByRole("button", { name: "New cheque" }));

    const creditSelect = (await screen.findByLabelText(/Credit account/i)) as HTMLSelectElement;
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
    await user.click(within(table).getByText("Legacy cheque"));

    const creditSelect = (await screen.findByLabelText(/Credit account/i)) as HTMLSelectElement;
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
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "New cheque" }));
    await user.click(screen.getByRole("checkbox", { name: /Create as series/i }));
    await user.selectOptions(screen.getByLabelText(/^Credit account/i), "1");
    await user.selectOptions(screen.getByLabelText(/^Debit account/i), "2");
    await user.type(screen.getByLabelText(/^Summary/i), "Snow");
    await user.type(screen.getByLabelText(/Starting cheque number/i), "1001");
    fireEvent.change(screen.getByLabelText(/First issue date/i), {
      target: { value: "2025-11-01" },
    });
    await user.type(screen.getByLabelText(/^Amount/i), "900");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => {
      expect(screen.getByText("Open cheque number already in use on this credit account")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Create series" })).toBeDisabled();

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
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    render(<ChequesSection accounts={accounts} parties={parties} />);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "New cheque" }));
    await user.click(screen.getByRole("checkbox", { name: /Create as series/i }));
    await user.selectOptions(screen.getByLabelText(/^Credit account/i), "1");
    await user.selectOptions(screen.getByLabelText(/^Debit account/i), "2");
    await user.type(screen.getByLabelText(/^Summary/i), "Series");
    await user.type(screen.getByLabelText(/Starting cheque number/i), "10");
    fireEvent.change(screen.getByLabelText(/First issue date/i), {
      target: { value: "2026-01-01" },
    });
    await user.type(screen.getByLabelText(/^Amount/i), "50");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Create series" })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "Create series" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/cheques/series") && c[1]?.method === "POST")).toBe(
        true,
      );
    });

    fetchMock.mockRestore();
  });
});
