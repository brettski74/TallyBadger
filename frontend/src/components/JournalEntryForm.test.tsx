import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import { JournalEntryForm, isBalanced, type LineDraft } from "./JournalEntryForm";

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

describe("isBalanced", () => {
  it("requires two lines, accounts, non-zero amounts, and zero sum", () => {
    const ok: LineDraft[] = [
      { key: "a", account_id: 1, amount: "100" },
      { key: "b", account_id: 2, amount: "-100" },
    ];
    expect(isBalanced(ok)).toBe(true);

    expect(isBalanced([{ key: "a", account_id: 1, amount: "1" }])).toBe(false);
    expect(
      isBalanced([
        { key: "a", account_id: 1, amount: "100" },
        { key: "b", account_id: 2, amount: "-99" },
      ]),
    ).toBe(false);
    expect(
      isBalanced([
        { key: "a", account_id: "", amount: "100" },
        { key: "b", account_id: 2, amount: "-100" },
      ]),
    ).toBe(false);
  });
});

describe("JournalEntryForm", () => {
  it("submits a balanced entry via onSubmit", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        initialEntryDate="2026-04-20"
        initialDescription=""
        initialLines={null}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );

    const user = userEvent.setup();
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[0]!, "1");
    await user.selectOptions(selects[1]!, "2");
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
      description: null,
      lines: [
        { account_id: 1, amount: "250.00" },
        { account_id: 2, amount: "-250.00" },
      ],
    });
  });

  it("keeps submit disabled while unbalanced", async () => {
    const onSubmit = vi.fn();
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        initialEntryDate="2026-04-20"
        initialDescription=""
        initialLines={null}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );

    const user = userEvent.setup();
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[0]!, "1");
    await user.selectOptions(selects[1]!, "2");
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
        initialEntryDate="2026-04-20"
        initialDescription=""
        initialLines={null}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );

    const user = userEvent.setup();
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[0]!, "1");
    await user.selectOptions(selects[1]!, "2");
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
      { key: "jl-1", account_id: 1, amount: "40" },
      { key: "jl-2", account_id: 2, amount: "-40" },
    ];
    render(
      <JournalEntryForm
        mode="edit"
        accounts={accounts}
        initialEntryDate="2026-03-01"
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
      description: "Rent",
      lines: [
        { account_id: 1, amount: "40" },
        { account_id: 2, amount: "-40" },
      ],
    });
  });

  it("does not list inactive accounts unless they appear on loaded lines", () => {
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        initialEntryDate="2026-04-20"
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
