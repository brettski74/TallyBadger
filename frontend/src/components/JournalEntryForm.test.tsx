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
import type { LedgerSettings } from "../api/settlements";

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

const arAccount: Account = {
  id: 10,
  name: "Accounts Receivable",
  type: "asset",
  is_active: true,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

const ledgerSettings: LedgerSettings = {
  accounts_receivable_account_id: 10,
  accounts_payable_account_id: 11,
  unearned_revenue_account_id: 12,
  prepaid_expenses_account_id: 13,
  unallocated_debits_account_id: null,
  unallocated_credits_account_id: null,
  default_cheque_credit_account_id: null,
  default_cheque_debit_account_id: null,
  default_cash_account_id: null,
  max_attachment_upload_bytes: 5_242_880,
  max_cheque_series_count: 12,
  scanner_device_uri: null,
  max_scanned_pages: 1,
  scan_dpi: 300,
  scan_color_mode: "greyscale",
  pdf_page_size: "us-letter",
  updated_at: "2026-04-01T00:00:00Z",
};

const planTargetAccountByPlanId = new Map<number, number>([[7, 2], [9, 2]]);

const urAccount: Account = {
  id: 12,
  name: "Unearned Revenue",
  type: "liability",
  is_active: true,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

const accrualAccounts = [...accounts, arAccount, urAccount];

const accrualLedgerSettings: LedgerSettings = {
  ...ledgerSettings,
  default_cash_account_id: 1,
};

function accrualSettlementFormProps(overrides: Record<string, unknown> = {}) {
  return {
    mode: "edit" as const,
    accounts: accrualAccounts,
    parties,
    initialEntryDate: "2026-07-01",
    initialSummary: "July rent",
    initialDescription: "",
    reviewMessages: [],
    initialLines: [
      { key: "pl", account_id: 2, party_id: 1, amount: "-1500.00", obligation_id: "" },
      { key: "jl-20", account_id: 10, party_id: 1, amount: "1500.00", obligation_id: "" },
    ],
    accrualPlanId: 9,
    accrualPlanName: "Monthly rent",
    settlementAllocations: [],
    sourceObligationId: 44,
    openAmount: "1500.00",
    sourceLineId: 20,
    ledgerSettings: accrualLedgerSettings,
    planTargetAccountByPlanId,
    onSubmit: vi.fn().mockResolvedValue(undefined),
    onCancel: () => {},
    onRevert: () => {},
    ...overrides,
  };
}

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
        onRevert={() => {}}
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
        onRevert={() => {}}
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
        onRevert={() => {}}
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
        onRevert={() => {}}
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
        onRevert={() => {}}
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

  it("invokes onRevert when Ctrl+Shift+D is pressed while focus is inside the form", () => {
    const onRevert = vi.fn();
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
        onCancel={() => {}}
        onRevert={onRevert}
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

    expect(onRevert).toHaveBeenCalledTimes(1);
  });

  it("invokes onRevert with Ctrl+Shift+D when the entry is unbalanced", () => {
    const onRevert = vi.fn();
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
        onCancel={() => {}}
        onRevert={onRevert}
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

    expect(onRevert).toHaveBeenCalledTimes(1);
  });

  it("invokes onRevert when Ctrl+Shift+D is pressed from an input inside a shadow root in the form", () => {
    const onRevert = vi.fn();
    const { container } = render(
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
        onCancel={() => {}}
        onRevert={onRevert}
      />,
    );

    const form = container.querySelector("form");
    expect(form).toBeTruthy();
    const host = document.createElement("div");
    form!.appendChild(host);
    const shadow = host.attachShadow({ mode: "open" });
    const inner = document.createElement("input");
    shadow.appendChild(inner);
    inner.focus();

    fireEvent.keyDown(inner, {
      key: "d",
      code: "KeyD",
      ctrlKey: true,
      shiftKey: true,
      bubbles: true,
    });

    expect(onRevert).toHaveBeenCalledTimes(1);
  });

  it("invokes onRevert when Ctrl+Shift+D is pressed with keydown target document.body (no field focused)", () => {
    const onRevert = vi.fn();
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
        onCancel={() => {}}
        onRevert={onRevert}
      />,
    );

    fireEvent.keyDown(document.body, {
      key: "d",
      code: "KeyD",
      ctrlKey: true,
      shiftKey: true,
      bubbles: true,
    });

    expect(onRevert).toHaveBeenCalledTimes(1);
  });

  it("invokes onRevert when Ctrl+Shift+D is pressed while focus is outside the form", () => {
    const onRevert = vi.fn();
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
          onCancel={() => {}}
          onRevert={onRevert}
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

    expect(onRevert).toHaveBeenCalledTimes(1);
  });

  it("invokes onCancel when Escape is pressed", () => {
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
        onRevert={() => {}}
      />,
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("invokes onRevert when Meta+Shift+D is pressed while focus is inside the form", () => {
    const onRevert = vi.fn();
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
        onCancel={() => {}}
        onRevert={onRevert}
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

    expect(onRevert).toHaveBeenCalledTimes(1);
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
        onRevert={() => {}}
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
        onRevert={() => {}}
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
        onRevert={() => {}}
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
        onRevert={() => {}}
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
        onRevert={() => {}}
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

  describe("manual obligation settlement (#272)", () => {
    it("includes obligation_id on bridge lines in the submit payload", async () => {
      const onSubmit = vi.fn().mockResolvedValue(undefined);
      const initialLines: LineDraft[] = [
        {
          key: "a",
          account_id: 10,
          party_id: 1,
          amount: "100.00",
          obligation_id: 55,
        },
        { key: "b", account_id: 1, party_id: "", amount: "-100.00", obligation_id: "" },
      ];
      render(
        <JournalEntryForm
          mode="edit"
          accounts={[...accounts, arAccount]}
          parties={parties}
          initialEntryDate="2026-04-20"
          initialSummary="Rent receipt"
          initialDescription=""
          reviewMessages={[]}
          initialLines={initialLines}
          ledgerSettings={ledgerSettings}
          planTargetAccountByPlanId={planTargetAccountByPlanId}
          onSubmit={onSubmit}
          onCancel={() => {}}
          onRevert={() => {}}
        />,
      );

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /Save changes/ }));

      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const payload = onSubmit.mock.calls[0]![0];
      expect(payload.lines).toEqual([
        { account_id: 10, party_id: 1, amount: "100.00", obligation_id: 55 },
        { account_id: 1, party_id: null, amount: "-100.00" },
      ]);
    });

    it("labels saved obligations with source summary instead of id only", () => {
      vi.spyOn(global, "fetch").mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

      const initialLines: LineDraft[] = [
        {
          key: "a",
          account_id: 10,
          party_id: 1,
          amount: "100.00",
          obligation_id: 48,
          obligation_source_entry_summary: "Snow removal 2026-02",
        },
        { key: "b", account_id: 1, party_id: "", amount: "-100.00", obligation_id: "" },
      ];
      render(
        <JournalEntryForm
          mode="edit"
          accounts={[...accounts, arAccount]}
          parties={parties}
          initialEntryDate="2026-04-20"
          initialSummary="Rent receipt"
          initialDescription=""
          reviewMessages={[]}
          initialLines={initialLines}
          ledgerSettings={ledgerSettings}
          planTargetAccountByPlanId={planTargetAccountByPlanId}
          onSubmit={vi.fn()}
          onCancel={() => {}}
          onRevert={() => {}}
        />,
      );

      const obligationSelect = screen
        .getAllByRole("combobox")
        .find((el) => String(el.getAttribute("aria-label")).startsWith("Obligation for line"));
      expect(obligationSelect).toHaveValue("48");
      expect(
        obligationSelect?.querySelector('option[value="48"]')?.textContent,
      ).toBe("#48 — Snow removal 2026-02 (saved)");
    });

    it("marks the linked obligation (saved) when it is still in the open list", async () => {
      vi.spyOn(global, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify([
            {
              id: 48,
              party_id: 1,
              accrual_plan_id: 7,
              source_entry_id: 1,
              source_entry_date: "2026-02-01",
              source_entry_summary: "Snow removal 2026-02",
              obligation_type: "receivable",
              status: "partially_settled",
              original_amount: "1500.00",
              open_amount: "500.00",
              due_date: null,
            },
            {
              id: 49,
              party_id: 1,
              accrual_plan_id: 7,
              source_entry_id: 2,
              source_entry_date: "2026-03-01",
              source_entry_summary: "March rent",
              obligation_type: "receivable",
              status: "open",
              original_amount: "1000.00",
              open_amount: "1000.00",
              due_date: null,
            },
          ]),
          { status: 200 },
        ),
      );

      const initialLines: LineDraft[] = [
        {
          key: "a",
          account_id: 10,
          party_id: 1,
          amount: "100.00",
          obligation_id: 48,
          obligation_source_entry_summary: "Snow removal 2026-02",
        },
        { key: "b", account_id: 1, party_id: "", amount: "-100.00", obligation_id: "" },
      ];
      render(
        <JournalEntryForm
          mode="edit"
          accounts={[...accounts, arAccount]}
          parties={parties}
          initialEntryDate="2026-04-20"
          initialSummary="Rent receipt"
          initialDescription=""
          reviewMessages={[]}
          initialLines={initialLines}
          ledgerSettings={ledgerSettings}
          planTargetAccountByPlanId={planTargetAccountByPlanId}
          onSubmit={vi.fn()}
          onCancel={() => {}}
          onRevert={() => {}}
        />,
      );

      const obligationSelect = screen
        .getAllByRole("combobox")
        .find((el) => String(el.getAttribute("aria-label")).startsWith("Obligation for line"));
      await waitFor(() => {
        expect(obligationSelect?.querySelector('option[value="49"]')).toBeTruthy();
      });
      expect(obligationSelect?.querySelector('option[value="48"]')?.textContent).toBe(
        "#48 — Snow removal 2026-02 (saved)",
      );
      expect(obligationSelect?.querySelector('option[value="49"]')?.textContent).toBe(
        "#49 — March rent (1000.00 open)",
      );
    });

    it("locks account and party while obligation is set", async () => {
      vi.spyOn(global, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify([
            {
              id: 55,
              party_id: 1,
              accrual_plan_id: 7,
              source_entry_id: 1,
              source_entry_date: "2026-03-01",
              source_entry_summary: "March rent",
              obligation_type: "receivable",
              status: "open",
              original_amount: "100.00",
              open_amount: "100.00",
              due_date: null,
            },
          ]),
          { status: 200 },
        ),
      );

      render(
        <JournalEntryForm
          mode="create"
          accounts={[...accounts, arAccount]}
          parties={parties}
          initialEntryDate="2026-04-20"
          initialSummary="Rent receipt"
          initialDescription=""
          reviewMessages={[]}
          initialLines={null}
          ledgerSettings={ledgerSettings}
          planTargetAccountByPlanId={planTargetAccountByPlanId}
          onSubmit={vi.fn()}
          onCancel={() => {}}
          onRevert={() => {}}
        />,
      );

      const user = userEvent.setup();
      const accountSelects = screen
        .getAllByRole("combobox")
        .filter((el) => String(el.getAttribute("aria-label")).startsWith("Account for line"));
      const partySelects = screen
        .getAllByRole("combobox")
        .filter((el) => String(el.getAttribute("aria-label")).startsWith("Party for line"));
      const obligationSelects = screen
        .getAllByRole("combobox")
        .filter((el) => String(el.getAttribute("aria-label")).startsWith("Obligation for line"));

      await user.selectOptions(accountSelects[0]!, "2");
      await user.selectOptions(partySelects[0]!, "1");
      await waitFor(() => {
        expect(obligationSelects[0]!.querySelectorAll("option").length).toBeGreaterThan(1);
      });
      await user.selectOptions(obligationSelects[0]!, "55");

      expect(accountSelects[0]).toBeDisabled();
      expect(partySelects[0]).toBeDisabled();
      expect(accountSelects[0]).toHaveValue("10");
      expect(screen.getAllByPlaceholderText("100.00 or -100.00")[0]).toHaveValue("-100.00");
    });

    it("restores plan P&L when clearing obligation from a bridge line", async () => {
      vi.spyOn(global, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify([
            {
              id: 55,
              party_id: 1,
              accrual_plan_id: 7,
              source_entry_id: 1,
              source_entry_date: "2026-03-01",
              source_entry_summary: "March rent",
              obligation_type: "receivable",
              status: "partially_settled",
              original_amount: "100.00",
              open_amount: "50.00",
              due_date: null,
            },
          ]),
          { status: 200 },
        ),
      );

      render(
        <JournalEntryForm
          mode="edit"
          accounts={[...accounts, arAccount]}
          parties={parties}
          initialEntryDate="2026-04-20"
          initialSummary="Rent receipt"
          initialDescription=""
          reviewMessages={[]}
          initialLines={[
            {
              key: "a",
              account_id: 10,
              party_id: 1,
              amount: "50.00",
              obligation_id: 55,
              obligation_source_entry_summary: "March rent",
              obligation_target_account_id: 2,
            },
            { key: "b", account_id: 1, party_id: "", amount: "-50.00", obligation_id: "" },
          ]}
          ledgerSettings={ledgerSettings}
          planTargetAccountByPlanId={planTargetAccountByPlanId}
          onSubmit={vi.fn()}
          onCancel={() => {}}
          onRevert={() => {}}
        />,
      );

      const user = userEvent.setup();
      const obligationSelect = screen
        .getAllByRole("combobox")
        .find((el) => String(el.getAttribute("aria-label")).startsWith("Obligation for line"));
      const accountSelect = screen
        .getAllByRole("combobox")
        .find((el) => String(el.getAttribute("aria-label")).startsWith("Account for line"));

      await user.selectOptions(obligationSelect!, "");
      expect(accountSelect).toHaveValue("2");
      expect(accountSelect).not.toBeDisabled();
    });

    it("enables settlement editing for accrual entries with open amount", async () => {
      render(<JournalEntryForm {...accrualSettlementFormProps()} />);

      expect(screen.getByText(/accrual content is read-only/i)).toBeInTheDocument();
      expect(screen.getByText(/open amount 1500.00/i)).toBeInTheDocument();
      expect(screen.getByLabelText("Entry summary")).toBeDisabled();
      expect(screen.getByRole("button", { name: /Add line/ })).toBeEnabled();
      expect(screen.getByRole("button", { name: /Save changes/ })).toBeDisabled();

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /Add line/ }));

      const amountInputs = screen.getAllByPlaceholderText("100.00 or -100.00");
      const cashAmount = amountInputs.find((input) => !input.hasAttribute("disabled"));
      expect(cashAmount).toBeDefined();
      expect(screen.getByText("#44")).toBeInTheDocument();

      await user.clear(cashAmount!);
      await user.type(cashAmount!, "500.00");

      await waitFor(() => {
        const bridgeAmount = screen
          .getAllByPlaceholderText("100.00 or -100.00")
          .find(
            (input) =>
              input.hasAttribute("disabled") && (input as HTMLInputElement).value === "1000.00",
          );
        expect(bridgeAmount).toBeDefined();
      });
      expect(screen.getByRole("button", { name: /Save changes/ })).toBeEnabled();
    });

    it("disables add line when open amount is zero", () => {
      render(
        <JournalEntryForm
          {...accrualSettlementFormProps({
            openAmount: "0.00",
            initialLines: [
              { key: "pl", account_id: 2, party_id: 1, amount: "-1500.00", obligation_id: "" },
              { key: "jl-20", account_id: 10, party_id: 1, amount: "1500.00", obligation_id: "" },
            ],
          })}
        />,
      );

      expect(screen.getByText(/Obligation fully settled/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Add line/ })).toBeDisabled();
    });

    it("prefills default cash account on new settlement cash lines", async () => {
      render(<JournalEntryForm {...accrualSettlementFormProps()} />);
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /Add line/ }));

      const accountSelects = screen
        .getAllByRole("combobox")
        .filter((el) => String(el.getAttribute("aria-label")).startsWith("Account for line"));
      const editableAccount = accountSelects.find((el) => !(el as HTMLSelectElement).disabled);
      expect(editableAccount).toHaveValue("1");
    });

    it("keeps P&L and prepaid lines read-only", () => {
      render(
        <JournalEntryForm
          {...accrualSettlementFormProps({
            initialLines: [
              { key: "pl", account_id: 2, party_id: 1, amount: "-1500.00", obligation_id: "" },
              { key: "ur", account_id: 12, party_id: 1, amount: "500.00", obligation_id: "" },
              { key: "jl-20", account_id: 10, party_id: 1, amount: "1000.00", obligation_id: "" },
            ],
            openAmount: "1000.00",
          })}
        />,
      );

      const amountInputs = screen.getAllByPlaceholderText("100.00 or -100.00");
      const disabledAmounts = amountInputs.filter((input) => input.hasAttribute("disabled"));
      expect(disabledAmounts.map((input) => (input as HTMLInputElement).value)).toEqual(
        expect.arrayContaining(["-1500.00", "500.00", "1000.00"]),
      );
    });

    it("merges same-account cash lines on save", async () => {
      const onSubmit = vi.fn().mockResolvedValue(undefined);
      render(
        <JournalEntryForm
          {...accrualSettlementFormProps({
            onSubmit,
            initialLines: [
              { key: "pl", account_id: 2, party_id: 1, amount: "-1500.00", obligation_id: "" },
              { key: "jl-20", account_id: 10, party_id: 1, amount: "700.00", obligation_id: "" },
              { key: "cash-a", account_id: 1, party_id: 1, amount: "400.00", obligation_id: 44 },
            ],
          })}
        />,
      );

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /Add line/ }));
      const amountInputs = screen.getAllByPlaceholderText("100.00 or -100.00");
      const editableAmounts = amountInputs.filter((input) => !input.hasAttribute("disabled"));
      const newCashAmount = editableAmounts[editableAmounts.length - 1]!;
      await user.clear(newCashAmount);
      await user.type(newCashAmount, "100.00");

      await user.click(screen.getByRole("button", { name: /Save changes/ }));

      await waitFor(() => {
        expect(onSubmit).toHaveBeenCalledTimes(1);
      });
      const payload = onSubmit.mock.calls[0]![0] as { lines: { obligation_id?: number; amount: string }[] };
      const cashLines = payload.lines.filter((line) => line.obligation_id === 44);
      expect(cashLines).toHaveLength(1);
      expect(cashLines[0]?.amount).toBe("500.00");
    });

    it("enables cheque control only with one non-zero settlement cash line", async () => {
      render(<JournalEntryForm {...accrualSettlementFormProps()} />);
      expect(screen.getByLabelText("Link open cheque")).toBeDisabled();

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /Add line/ }));
      const amountInputs = screen.getAllByPlaceholderText("100.00 or -100.00");
      const cashAmount = amountInputs.find((input) => !input.hasAttribute("disabled"));
      await user.clear(cashAmount!);
      await user.type(cashAmount!, "500.00");

      expect(screen.getByLabelText("Link open cheque")).toBeEnabled();
    });

    it("shows unsettle banner when obligation is closed but cash lines remain", () => {
      render(
        <JournalEntryForm
          {...accrualSettlementFormProps({
            openAmount: "0.00",
            initialLines: [
              { key: "pl", account_id: 2, party_id: 1, amount: "-1500.00", obligation_id: "" },
              { key: "jl-30", account_id: 1, party_id: 1, amount: "1500.00", obligation_id: 44 },
            ],
          })}
        />,
      );

      expect(screen.getByText(/Remove settlement cash lines and save to unsettle/i)).toBeInTheDocument();
    });
  });
});
