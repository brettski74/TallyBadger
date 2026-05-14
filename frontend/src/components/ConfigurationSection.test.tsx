import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import { ConfigurationSection } from "./ConfigurationSection";

afterEach(() => {
  vi.restoreAllMocks();
});

const accounts: Account[] = [
  { id: 1, name: "Cash", type: "asset", is_active: true, created_at: "", updated_at: "" },
  { id: 2, name: "A/R", type: "asset", is_active: true, created_at: "", updated_at: "" },
  { id: 12, name: "Legacy A/R", type: "asset", is_active: false, created_at: "", updated_at: "" },
  { id: 3, name: "A/P", type: "liability", is_active: true, created_at: "", updated_at: "" },
  { id: 13, name: "Old Payable", type: "liability", is_active: false, created_at: "", updated_at: "" },
  { id: 4, name: "Unearned", type: "liability", is_active: true, created_at: "", updated_at: "" },
  { id: 10, name: "Unallocated Debits", type: "suspense", is_active: true, created_at: "", updated_at: "" },
  { id: 11, name: "Unallocated Credits", type: "suspense", is_active: true, created_at: "", updated_at: "" },
  { id: 20, name: "Stale suspense", type: "suspense", is_active: false, created_at: "", updated_at: "" },
];

describe("ConfigurationSection", () => {
  it("loads ledger settings and saves all five account roles", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            accounts_receivable_account_id: null,
            accounts_payable_account_id: null,
            unearned_revenue_account_id: null,
            unallocated_debits_account_id: null,
            unallocated_credits_account_id: null,
            updated_at: "2026-01-01T00:00:00Z",
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            accounts_receivable_account_id: 2,
            accounts_payable_account_id: 3,
            unearned_revenue_account_id: 4,
            unallocated_debits_account_id: 10,
            unallocated_credits_account_id: 11,
            updated_at: "2026-01-02T00:00:00Z",
          }),
          { status: 200 },
        ),
      );

    render(<ConfigurationSection accounts={accounts} />);
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByLabelText("Accounts receivable")).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText("Accounts receivable"), "2");
    await user.selectOptions(screen.getByLabelText("Accounts payable"), "3");
    await user.selectOptions(screen.getByLabelText("Unearned revenue"), "4");
    await user.selectOptions(screen.getByLabelText("Unallocated debits (default debit side)"), "10");
    await user.selectOptions(screen.getByLabelText("Unallocated credits (default credit side)"), "11");
    await user.click(screen.getByRole("button", { name: "Save configuration" }));

    const patchCall = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls.find(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patchCall).toBeTruthy();
    expect(JSON.parse(String(patchCall![1]!.body))).toEqual({
      accounts_receivable_account_id: 2,
      accounts_payable_account_id: 3,
      unearned_revenue_account_id: 4,
      unallocated_debits_account_id: 10,
      unallocated_credits_account_id: 11,
    });
  });

  it("shows inactive account in a role dropdown only when that setting already points at it", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          accounts_receivable_account_id: 12,
          accounts_payable_account_id: 3,
          unearned_revenue_account_id: 4,
          unallocated_debits_account_id: 20,
          unallocated_credits_account_id: 11,
          updated_at: "2026-01-01T00:00:00Z",
        }),
        { status: 200 },
      ),
    );

    render(<ConfigurationSection accounts={accounts} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Accounts receivable")).toHaveValue("12");
    });

    const arOptions = Array.from(
      screen.getByLabelText("Accounts receivable").querySelectorAll("option"),
    ).map((o) => o.textContent);
    expect(arOptions.some((t) => t?.includes("Legacy A/R") && t?.includes("inactive"))).toBe(true);

    const apOptions = Array.from(screen.getByLabelText("Accounts payable").querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(apOptions.some((t) => t?.includes("Old Payable"))).toBe(false);

    const drOptions = Array.from(
      screen.getByLabelText("Unallocated debits (default debit side)").querySelectorAll("option"),
    ).map((o) => o.textContent);
    expect(drOptions.some((t) => t?.includes("Stale suspense") && t?.includes("inactive"))).toBe(true);

    const crOptions = Array.from(
      screen.getByLabelText("Unallocated credits (default credit side)").querySelectorAll("option"),
    ).map((o) => o.textContent);
    expect(crOptions.some((t) => t?.includes("Stale suspense"))).toBe(false);
  });
});
