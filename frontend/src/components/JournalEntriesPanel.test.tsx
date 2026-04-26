import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import { JournalEntriesPanel } from "./JournalEntriesPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

const accounts: Account[] = [
  {
    id: 1,
    name: "Cash",
    type: "asset",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
  {
    id: 2,
    name: "Income",
    type: "revenue",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
];

const parties = [
  {
    id: 1,
    name: "Acme Yard Maintenance",
    role: "customer",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
];

describe("JournalEntriesPanel", () => {
  it("loads list and completes edit save path", async () => {
    const listPayload = [
      {
        id: 7,
        entry_date: "2026-04-10",
        summary: "Rent accrual",
        description: "Test",
        created_at: "2026-04-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
        debit_side_label: "Cash",
        credit_side_label: "Income",
        party_labels: "Acme Yard Maintenance",
        amount: "25.00",
      },
    ];
    const entryPayload = {
      id: 7,
      entry_date: "2026-04-10",
      summary: "Rent accrual",
      description: "Test",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
      lines: [
        { id: 10, account_id: 1, party_id: 1, amount: "25.00", account_name: "Cash", party_name: "Acme Yard Maintenance" },
        { id: 11, account_id: 2, party_id: 1, amount: "-25.00", account_name: "Income", party_name: "Acme Yard Maintenance" },
      ],
    };

    vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (/\/journal-entries\/7\/?$/.test(url)) {
        if (method === "PUT") {
          return new Response(
            JSON.stringify({ ...entryPayload, summary: "Updated summary", description: "Updated" }),
            { status: 200 },
          );
        }
        return new Response(JSON.stringify(entryPayload), { status: 200 });
      }
      if (url.includes("/journal-entries")) {
        return new Response(JSON.stringify(listPayload), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    expect(await screen.findByText("Rent accrual")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit" }));

    expect(await screen.findByRole("heading", { name: "Edit journal entry" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Entry description"));
    await user.type(screen.getByLabelText("Entry description"), "Updated");

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Journal entries" })).toBeInTheDocument();
    });
  });

  it("shows journal API error text from list failure", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "service unavailable" }), { status: 503 }),
    );

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("service unavailable");
  });
});
