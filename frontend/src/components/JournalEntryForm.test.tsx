import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import type { Cheque } from "../api/cheques";
import {
  JournalEntryForm,
  debitCreditTotals,
  isBalanced,
  linesMatchChequeFaceAmount,
  materialJournalLines,
  type LineDraft,
} from "./JournalEntryForm";
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
    match_patterns: [],
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

describe("debitCreditTotals and linesMatchChequeFaceAmount", () => {
  it("aggregates debits and credits from material lines", () => {
    const lines: LineDraft[] = [
      { key: "a", account_id: 1, party_id: "", amount: "40" },
      { key: "b", account_id: 1, party_id: "", amount: "60" },
      { key: "c", account_id: 2, party_id: "", amount: "-100" },
    ];
    expect(debitCreditTotals(lines)).toEqual({ debit: 100, credit: 100, complete: true });
    expect(linesMatchChequeFaceAmount(lines, "100")).toBe(true);
    expect(linesMatchChequeFaceAmount(lines, "-100")).toBe(true);
    expect(linesMatchChequeFaceAmount(lines, "99")).toBe(false);
  });

  it("treats no material lines as matching any cheque amount", () => {
    const blank: LineDraft[] = [
      { key: "a", account_id: "", party_id: "", amount: "" },
      { key: "b", account_id: "", party_id: "", amount: "" },
    ];
    expect(linesMatchChequeFaceAmount(blank, "999")).toBe(true);
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
        reviewMessages={[]}
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

    await user.click(screen.getByRole("button", { name: /Post entry/ }));

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
      requires_review: false,
      review_messages: [],
      cheque_id: null,
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
        reviewMessages={[]}
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

    expect(screen.getByRole("button", { name: /Post entry/ })).toBeDisabled();
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
        reviewMessages={[]}
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

    await user.click(screen.getByRole("button", { name: /Post entry/ }));

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
        reviewMessages={[]}
        initialLines={initialLines}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Save changes/ }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith({
      entry_date: "2026-03-01",
      summary: "Monthly rent",
      description: "Rent",
      lines: [
        { account_id: 1, party_id: null, amount: "40" },
        { account_id: 2, party_id: null, amount: "-40" },
      ],
      requires_review: false,
      review_messages: [],
      cheque_id: null,
    });
  });

  it("submits when Ctrl+S is pressed while focus is inside the form", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Rent accrual"
        initialDescription=""
        reviewMessages={[]}
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

    const summaryInput = screen.getByLabelText("Entry summary");
    summaryInput.focus();
    fireEvent.keyDown(summaryInput, { key: "s", code: "KeyS", ctrlKey: true, bubbles: true });

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });
  });

  it("invokes onCancel when Ctrl+Shift+D is pressed while focus is inside the form", () => {
    const onCancel = vi.fn();
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Rent accrual"
        initialDescription=""
        reviewMessages={[]}
        initialLines={null}
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    );

    const summaryInput = screen.getByLabelText("Entry summary");
    summaryInput.focus();
    fireEvent.keyDown(summaryInput, {
      key: "d",
      code: "KeyD",
      ctrlKey: true,
      shiftKey: true,
      bubbles: true,
    });

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("invokes onCancel with Ctrl+Shift+D when the entry is unbalanced", () => {
    const onCancel = vi.fn();
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Unbalanced"
        initialDescription=""
        reviewMessages={[]}
        initialLines={null}
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    );

    const summaryInput = screen.getByLabelText("Entry summary");
    summaryInput.focus();
    fireEvent.keyDown(summaryInput, {
      key: "d",
      code: "KeyD",
      ctrlKey: true,
      shiftKey: true,
      bubbles: true,
    });

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("does not invoke onCancel when Ctrl+Shift+D is pressed with focus outside the form", () => {
    const onCancel = vi.fn();
    render(
      <div>
        <JournalEntryForm
          mode="create"
          accounts={accounts}
          parties={parties}
          initialEntryDate="2026-04-20"
          initialSummary="Rent accrual"
          initialDescription=""
          reviewMessages={[]}
          initialLines={null}
          onSubmit={vi.fn()}
          onCancel={onCancel}
        />
        <button type="button">Outside</button>
      </div>,
    );

    screen.getByRole("button", { name: "Outside" }).focus();
    fireEvent.keyDown(document.activeElement ?? document.body, {
      key: "d",
      code: "KeyD",
      ctrlKey: true,
      shiftKey: true,
      bubbles: true,
    });

    expect(onCancel).not.toHaveBeenCalled();
  });

  it("invokes onCancel when Meta+Shift+D is pressed while focus is inside the form", () => {
    const onCancel = vi.fn();
    render(
      <JournalEntryForm
        mode="edit"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-03-01"
        initialSummary="Monthly rent"
        initialDescription=""
        reviewMessages={[]}
        initialLines={[
          { key: "jl-1", account_id: 1, party_id: "", amount: "40" },
          { key: "jl-2", account_id: 2, party_id: "", amount: "-40" },
        ]}
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    );

    const summaryInput = screen.getByLabelText("Entry summary");
    summaryInput.focus();
    fireEvent.keyDown(summaryInput, {
      key: "d",
      code: "KeyD",
      metaKey: true,
      shiftKey: true,
      bubbles: true,
    });

    expect(onCancel).toHaveBeenCalledTimes(1);
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
        reviewMessages={[]}
        initialLines={null}
        onSubmit={vi.fn()}
        onCancel={() => {}}
      />,
    );
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options.some((t) => t?.includes("Retired"))).toBe(false);
  });

  it("each line account list includes only that line's loaded inactive id, not other lines' (can revert after a temporary change)", async () => {
    const initialLines: LineDraft[] = [
      { key: "a", account_id: 1, party_id: "", amount: "10" },
      { key: "b", account_id: 3, party_id: "", amount: "-10" },
    ];
    render(
      <JournalEntryForm
        mode="edit"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Split"
        initialDescription=""
        reviewMessages={[]}
        initialLines={initialLines}
        onSubmit={vi.fn()}
        onCancel={() => {}}
      />,
    );
    const user = userEvent.setup();
    const accountSelects = screen
      .getAllByRole("combobox")
      .filter((el) => String(el.getAttribute("aria-label")).startsWith("Account for line"));

    const optionsForLine = (idx: number) =>
      Array.from(accountSelects[idx]!.querySelectorAll("option")).map((o) => o.textContent?.trim());

    expect(optionsForLine(0).some((t) => t?.includes("Retired"))).toBe(false);
    expect(optionsForLine(1).some((t) => t?.includes("Retired"))).toBe(true);

    await user.selectOptions(accountSelects[1]!, "1");
    expect(optionsForLine(1).some((t) => t?.includes("Retired"))).toBe(true);

    await user.selectOptions(accountSelects[1]!, "3");
    expect(optionsForLine(1).some((t) => t?.includes("Retired"))).toBe(true);
    expect(optionsForLine(0).some((t) => t?.includes("Retired"))).toBe(false);
  });

  const openCheque: Cheque = {
    id: 99,
    credit_account_id: 1,
    debit_account_id: 2,
    summary: "Supplier payment",
    cheque_number: 42,
    issue_date: "2026-04-01",
    cleared_date: null,
    amount: "100.00",
    party_id: 1,
    status: "open",
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  };

  it("confirms before replacing lines when the cheque amount does not match entry totals", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Rent accrual"
        initialDescription=""
        reviewMessages={[]}
        initialLines={null}
        chequeLinkChoices={[openCheque]}
        onSubmit={vi.fn()}
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

    await user.selectOptions(screen.getByLabelText("Link open cheque"), String(openCheque.id));

    expect(confirmSpy).toHaveBeenCalled();
    const [confirmMessage] = confirmSpy.mock.calls[0] ?? [];
    expect(confirmMessage).toContain("$250.00");
    expect(confirmMessage).toContain("$100.00");

    expect(amountInputs[0]).toHaveValue("250.00");
    expect(amountInputs[1]).toHaveValue("-250.00");
    expect(screen.getByLabelText("Entry summary")).toHaveValue("Rent accrual");

    confirmSpy.mockReturnValue(true);
    await user.selectOptions(screen.getByLabelText("Link open cheque"), String(openCheque.id));

    await waitFor(() => {
      expect(screen.getByLabelText("Entry summary")).toHaveValue("Supplier payment");
    });
    const amountsAfter = screen.getAllByPlaceholderText("100.00 or -100.00");
    expect(amountsAfter[0]).toHaveValue("100.00");
    expect(amountsAfter[1]).toHaveValue("-100.00");

    confirmSpy.mockRestore();
  });

  it("formats confirmation amounts with thousands separators when large", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const bigCheque: Cheque = {
      ...openCheque,
      id: 101,
      amount: "1234567.89",
    };
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Rent accrual"
        initialDescription=""
        reviewMessages={[]}
        initialLines={null}
        chequeLinkChoices={[bigCheque]}
        onSubmit={vi.fn()}
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
    await user.type(amountInputs[0]!, "99.00");
    await user.clear(amountInputs[1]!);
    await user.type(amountInputs[1]!, "-99.00");

    await user.selectOptions(screen.getByLabelText("Link open cheque"), String(bigCheque.id));

    const [confirmMessage] = confirmSpy.mock.calls[0] ?? [];
    expect(confirmMessage).toContain("$1,234,567.89");
    expect(confirmMessage).toContain("$99.00");

    confirmSpy.mockRestore();
  });

  it("does not confirm when line totals already match the cheque face", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <JournalEntryForm
        mode="create"
        accounts={accounts}
        parties={parties}
        initialEntryDate="2026-04-20"
        initialSummary="Rent accrual"
        initialDescription=""
        reviewMessages={[]}
        initialLines={null}
        chequeLinkChoices={[openCheque]}
        onSubmit={vi.fn()}
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
    await user.type(amountInputs[0]!, "100.00");
    await user.clear(amountInputs[1]!);
    await user.type(amountInputs[1]!, "-100.00");

    await user.selectOptions(screen.getByLabelText("Link open cheque"), String(openCheque.id));

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Entry summary")).toHaveValue("Supplier payment");

    confirmSpy.mockRestore();
  });
});
