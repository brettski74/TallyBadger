import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import { JournalEntryForm, isBalanced, materialJournalLines, type LineDraft } from "./JournalEntryForm";
import type { Party } from "../api/parties";

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
    name: "Rental income",
    type: "revenue",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
  {
    id: 3,
    name: "Retired",
    type: "expense",
    is_active: false,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
];

const parties: Party[] = [
  {
    id: 1,
    name: "Acme Yard Maintenance",
    role: "customer",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
];

describe("isBalanced", () => {
  it("requires two lines, accounts, non-zero amounts, and zero sum", () => {
    const ok: LineDraft[] = [
      { key: "a", account_id: 1, party_id: "", amount: "100" },
      { key: "b", account_id: 2, party_id: "", amount: "-100" },
    ];
    expect(isBalanced(ok)).toBe(true);

    expect(isBalanced([{ key: "a", account_id: 1, party_id: "", amount: "1" }])).toBe(false);
    expect(
      isBalanced([
        { key: "a", account_id: 1, party_id: "", amount: "100" },
        { key: "b", account_id: 2, party_id: "", amount: "-99" },
      ]),
    ).toBe(false);
    expect(
      isBalanced([
        { key: "a", account_id: "", party_id: "", amount: "100" },
        { key: "b", account_id: 2, party_id: "", amount: "-100" },
      ]),
    ).toBe(false);
  });

  it("ignores completely blank rows when balancing", () => {
    const lines: LineDraft[] = [
      { key: "a", account_id: 1, party_id: "", amount: "100" },
      { key: "b", account_id: 2, party_id: "", amount: "-100" },
      { key: "c", account_id: "", party_id: "", amount: "" },
    ];
    expect(materialJournalLines(lines)).toHaveLength(2);
    expect(isBalanced(lines)).toBe(true);
  });
});

describe("JournalEntryForm", () => {
  it("submits a balanced entry via onSubmit", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Rent accrual"
        initialDescription=""
        initialLines={null}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );

    const user = userEvent.setup();
    const accountSelects = screen
      .getAllByRole("combobox")
      .filter((el) => String(el.getAttribute("aria-label")).startsWith("Account for line"));
    await user.selectOptions(accountSelects[0]!, "1");
    await user.selectOptions(accountSelects[1]!, "2");
    const amountInputs = screen.getAllByPlaceholderText("100.00 or -100.00");
    await user.clear(amountInputs[0]!);
    await user.type(amountInputs[0]!, "250.00");
    await user.clear(amountInputs[1]!);
    await user.type(amountInputs[1]!, "-250.00");

    await user.click(screen.getByRole("button", { name: "Post entry" }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });
    expect(onSubmit).toHaveBeenCalledWith({
      entry_date: "2026-04-20",
      summary: "Rent accrual",
      description: null,
      lines: [
        { account_id: 1, party_id: null, amount: "250.00" },
        { account_id: 2, party_id: null, amount: "-250.00" },
      ],
    });
  });

  it("keeps submit disabled while unbalanced", async () => {
    const onSubmit = vi.fn();
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Unbalanced"
        initialDescription=""
        initialLines={null}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );

    const user = userEvent.setup();
    const accountSelects = screen
      .getAllByRole("combobox")
      .filter((el) => String(el.getAttribute("aria-label")).startsWith("Account for line"));
    await user.selectOptions(accountSelects[0]!, "1");
    await user.selectOptions(accountSelects[1]!, "2");
    const amountInputs = screen.getAllByPlaceholderText("100.00 or -100.00");
    await user.clear(amountInputs[0]!);
    await user.type(amountInputs[0]!, "100");
    await user.clear(amountInputs[1]!);
    await user.type(amountInputs[1]!, "-50");

    expect(screen.getByRole("button", { name: "Post entry" })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("surfaces API failures from onSubmit", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("journal entry is not balanced"));
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="API error test"
        initialDescription=""
        initialLines={null}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );

    const user = userEvent.setup();
    const accountSelects = screen
      .getAllByRole("combobox")
      .filter((el) => String(el.getAttribute("aria-label")).startsWith("Account for line"));
    await user.selectOptions(accountSelects[0]!, "1");
    await user.selectOptions(accountSelects[1]!, "2");
    const amountInputs = screen.getAllByPlaceholderText("100.00 or -100.00");
    await user.clear(amountInputs[0]!);
    await user.type(amountInputs[0]!, "10");
    await user.clear(amountInputs[1]!);
    await user.type(amountInputs[1]!, "-10");

    await user.click(screen.getByRole("button", { name: "Post entry" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("journal entry is not balanced");
  });

  it("edit mode saves with Save changes label", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const initialLines: LineDraft[] = [
      { key: "jl-1", account_id: 1, party_id: "", amount: "40" },
      { key: "jl-2", account_id: 2, party_id: "", amount: "-40" },
    ];
    render(
      <JournalEntryForm
        mode="edit"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-03-01"
        initialSummary="Monthly rent"
        initialDescription="Rent"
        initialLines={initialLines}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith({
      entry_date: "2026-03-01",
      summary: "Monthly rent",
      description: "Rent",
      lines: [
        { account_id: 1, party_id: null, amount: "40" },
        { account_id: 2, party_id: null, amount: "-40" },
      ],
    });
  });

  it("does not list inactive accounts unless they appear on loaded lines", () => {
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Show active accounts"
        initialDescription=""
        initialLines={null}
        onSubmit={vi.fn()}
        onCancel={() => {}}
      />,
    );
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options.some((t) => t?.includes("Retired"))).toBe(false);
  });
});
