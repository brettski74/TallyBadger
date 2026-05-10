import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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

describe("ChequesSection", () => {
  it("requests cheques with status=open by default", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    const firstUrl = String(fetchMock.mock.calls[0][0]);
    expect(firstUrl).toContain("/cheques");
    expect(firstUrl).toContain("status=open");
  });

  it("requests status=all when filter is All", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    render(<ChequesSection accounts={accounts} parties={parties} />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    fetchMock.mockClear();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter cheques by status"), "all");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("status=all");
  });

  it("does not offer Void on cleared cheque rows", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify([
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
        ]),
        { status: 200 },
      ),
    );

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const table = await screen.findByRole("table");
    const row = within(table).getByRole("row", { name: /Cleared one/i });
    expect(within(row).queryByRole("button", { name: "Void" })).not.toBeInTheDocument();
  });

  it("shows Re-open for void cheque rows", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify([
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
        ]),
        { status: 200 },
      ),
    );

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const table = await screen.findByRole("table");
    expect(within(table).getByRole("button", { name: "Re-open" })).toBeInTheDocument();
  });

  it("has no status dropdown on the edit form", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify([
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
        ]),
        { status: 200 },
      ),
    );

    render(<ChequesSection accounts={accounts} parties={parties} />);

    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await user.click(within(table).getByText("Open one"));

    const selects = screen.getAllByRole("combobox");
    const statusField = selects.find((el) => el.getAttribute("aria-label") === "Cheque status");
    expect(statusField).toBeUndefined();
  });
});
