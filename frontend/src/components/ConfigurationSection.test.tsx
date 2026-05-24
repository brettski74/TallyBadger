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
    await user.click(screen.getByRole("button", { name: /Save configuration/i }));

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

  function ledgerSettingsResponse() {
    return new Response(
      JSON.stringify({
        accounts_receivable_account_id: null,
        accounts_payable_account_id: null,
        unearned_revenue_account_id: null,
        unallocated_debits_account_id: null,
        unallocated_credits_account_id: null,
        updated_at: "2026-01-01T00:00:00Z",
      }),
      { status: 200 },
    );
  }

  it("restore success without deprecation shows only generic success", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(ledgerSettingsResponse())
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "imported" }), { status: 200 }));

    render(<ConfigurationSection accounts={accounts} />);
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Restore from ZIP/i })).toBeInTheDocument();
    });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["zip"], "snap.zip", { type: "application/zip" });
    await user.upload(input, file);

    await waitFor(() => {
      expect(screen.getByText(/Restore finished successfully/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/deprecated/i)).not.toBeInTheDocument();
  });

  it("restore success shows deprecation warning after success line", async () => {
    const deprecation =
      "This backup uses snapshot format version 1.5.0. Support is deprecated.";
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(ledgerSettingsResponse())
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ status: "imported", format_deprecation_warning: deprecation }),
          { status: 200 },
        ),
      );

    render(<ConfigurationSection accounts={accounts} />);
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Restore from ZIP/i })).toBeInTheDocument();
    });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["zip"], "snap.zip", { type: "application/zip" }));

    await waitFor(() => {
      expect(screen.getByText(deprecation)).toBeInTheDocument();
    });
    const success = screen.getByText(/Restore finished successfully/i);
    const warning = screen.getByText(deprecation);
    expect(
      success.compareDocumentPosition(warning) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("restore failure shows error only, not deprecation warning", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(ledgerSettingsResponse())
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Unsupported format" }), { status: 400 }));

    render(<ConfigurationSection accounts={accounts} />);
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Restore from ZIP/i })).toBeInTheDocument();
    });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["zip"], "bad.zip", { type: "application/zip" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Unsupported format/i);
    });
    expect(screen.queryByText(/Restore finished successfully/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/deprecated/i)).not.toBeInTheDocument();
  });
});
