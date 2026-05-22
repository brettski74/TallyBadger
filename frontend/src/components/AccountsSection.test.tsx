import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AccountsSection } from "./AccountsSection";

afterEach(() => {
  vi.restoreAllMocks();
});

const baseAccount = {
  id: 5,
  name: "Petty Cash",
  type: "asset" as const,
  is_active: true,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

describe("AccountsSection", () => {
  it("does not PATCH when rename confirm is declined", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const onAccountUpdated = vi.fn();
    render(
      <AccountsSection
        accounts={[baseAccount]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={onAccountUpdated}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Edit account Petty Cash/ }));
    await user.clear(screen.getByLabelText("Edit name for account 5"));
    await user.type(screen.getByLabelText("Edit name for account 5"), "Spare Cash");
    await user.click(screen.getByRole("button", { name: /Save changes \(Ctrl\+S\)|Save changes \(⌘\+S\)/ }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(String(confirmSpy.mock.calls[0][0])).toContain("CEL");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(onAccountUpdated).not.toHaveBeenCalled();
  });

  it("PATCHes after confirms and calls onAccountUpdated", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const updated = {
      ...baseAccount,
      name: "Spare Cash",
      type: "liability" as const,
      updated_at: "2026-05-01T00:00:00Z",
    };
    let patched = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/accounts/5") && init?.method === "PATCH") {
        patched = true;
        expect(JSON.parse(String(init?.body))).toEqual({ name: "Spare Cash", type: "liability" });
        return new Response(JSON.stringify(updated), { status: 200 });
      }
      return new Response("unexpected fetch", { status: 500 });
    });

    const onAccountUpdated = vi.fn();
    render(
      <AccountsSection
        accounts={[baseAccount]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={onAccountUpdated}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Edit account Petty Cash/ }));
    await user.clear(screen.getByLabelText("Edit name for account 5"));
    await user.type(screen.getByLabelText("Edit name for account 5"), "Spare Cash");
    await user.selectOptions(screen.getByLabelText("Edit type for account 5"), "liability");
    await user.click(screen.getByRole("button", { name: /Save changes \(Ctrl\+S\)|Save changes \(⌘\+S\)/ }));

    expect(patched).toBe(true);
    expect(onAccountUpdated).toHaveBeenCalledWith(updated);
  });

  it("POSTs inline create and calls onAccountCreated", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const created = {
      id: 9,
      name: "Repairs",
      type: "expense" as const,
      is_active: true,
      created_at: "2026-05-01T00:00:00Z",
      updated_at: "2026-05-01T00:00:00Z",
    };
    let posted = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/accounts") && init?.method === "POST") {
        posted = true;
        expect(JSON.parse(String(init?.body))).toEqual({ name: "Repairs", type: "expense", is_active: true });
        return new Response(JSON.stringify(created), { status: 201 });
      }
      return new Response("unexpected fetch", { status: 500 });
    });

    const onAccountCreated = vi.fn();
    render(
      <AccountsSection
        accounts={[]}
        loading={false}
        error={null}
        onAccountCreated={onAccountCreated}
        onAccountUpdated={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Create account/i }));
    await user.type(screen.getByLabelText("New account name"), "Repairs");
    await user.selectOptions(screen.getByLabelText("New account type"), "expense");
    await user.click(screen.getByRole("button", { name: /Save new account \(Ctrl\+S\)|Save new account \(⌘\+S\)/ }));

    expect(posted).toBe(true);
    expect(onAccountCreated).toHaveBeenCalledWith(created);
  });

  it("revert on inline create clears draft but keeps the row open", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(
      <AccountsSection
        accounts={[]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Create account/i }));
    await user.type(screen.getByLabelText("New account name"), "Draft");
    await user.click(screen.getByRole("button", { name: /Discard \(Ctrl\+Shift\+D\)|Discard \(⌘\+Shift\+D\)/ }));

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByLabelText("New account name")).toHaveValue("");
  });

  it("Escape on inline create closes without saving", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(
      <AccountsSection
        accounts={[]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Create account/i }));
    await user.type(screen.getByLabelText("New account name"), "Draft");
    fireEvent.keyDown(document, { key: "Escape" });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("New account name")).not.toBeInTheDocument();
  });

  it("Ctrl+Shift+N opens inline create when not already creating", async () => {
    render(
      <AccountsSection
        accounts={[]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    fireEvent.keyDown(document, { key: "n", code: "KeyN", ctrlKey: true, shiftKey: true });
    const nameInput = screen.getByLabelText("New account name");
    expect(nameInput).toBeInTheDocument();
    expect(nameInput).toHaveFocus();
  });

  it("focuses the name field when Create account is clicked", async () => {
    render(
      <AccountsSection
        accounts={[baseAccount]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Create account/i }));
    const nameInput = screen.getByLabelText("New account name");
    expect(nameInput).toHaveFocus();
  });

  it("PATCHes is_active from list deactivate after confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const updated = { ...baseAccount, is_active: false, updated_at: "2026-05-02T00:00:00Z" };
    let patched = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/accounts/5") && init?.method === "PATCH") {
        patched = true;
        expect(JSON.parse(String(init?.body))).toEqual({ is_active: false });
        return new Response(JSON.stringify(updated), { status: 200 });
      }
      return new Response("unexpected fetch", { status: 500 });
    });

    const onAccountUpdated = vi.fn();
    render(
      <AccountsSection
        accounts={[baseAccount]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={onAccountUpdated}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Deactivate account Petty Cash/ }));

    expect(patched).toBe(true);
    expect(onAccountUpdated).toHaveBeenCalledWith(updated);
  });

  it("PATCHes is_active on list reactivate without confirm", async () => {
    const inactive = { ...baseAccount, is_active: false };
    const updated = { ...inactive, is_active: true, updated_at: "2026-05-02T00:00:00Z" };
    const confirmSpy = vi.spyOn(window, "confirm");
    let patched = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/accounts/5") && init?.method === "PATCH") {
        patched = true;
        expect(JSON.parse(String(init?.body))).toEqual({ is_active: true });
        return new Response(JSON.stringify(updated), { status: 200 });
      }
      return new Response("unexpected fetch", { status: 500 });
    });

    const onAccountUpdated = vi.fn();
    render(
      <AccountsSection
        accounts={[inactive]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={onAccountUpdated}
      />,
    );
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter accounts by active status"), "inactive");
    await user.click(screen.getByRole("button", { name: /Reactivate account Petty Cash/ }));

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(patched).toBe(true);
    expect(onAccountUpdated).toHaveBeenCalledWith(updated);
  });

  const inactiveAccount = {
    ...baseAccount,
    id: 6,
    name: "Old Vault",
    type: "asset" as const,
    is_active: false,
    updated_at: "2026-04-02T00:00:00Z",
  };

  it("by default lists only active accounts", () => {
    render(
      <AccountsSection
        accounts={[baseAccount, inactiveAccount]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    expect(screen.getByText("Petty Cash")).toBeInTheDocument();
    expect(screen.queryByText("Old Vault")).not.toBeInTheDocument();
  });

  it("lists inactive accounts when Active filter is All", async () => {
    const user = userEvent.setup();
    render(
      <AccountsSection
        accounts={[baseAccount, inactiveAccount]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    await user.selectOptions(screen.getByLabelText("Filter accounts by active status"), "all");
    expect(screen.getByText("Old Vault")).toBeInTheDocument();
  });

  it("lists only inactive accounts when filter is Inactive only", async () => {
    const user = userEvent.setup();
    render(
      <AccountsSection
        accounts={[baseAccount, inactiveAccount]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    await user.selectOptions(screen.getByLabelText("Filter accounts by active status"), "inactive");
    expect(screen.queryByText("Petty Cash")).not.toBeInTheDocument();
    expect(screen.getByText("Old Vault")).toBeInTheDocument();
  });

  it("filters by name glob and clears when name is cleared", async () => {
    const expenseAcc = {
      ...baseAccount,
      id: 7,
      name: "Repairs Expense",
      type: "expense" as const,
    };
    const user = userEvent.setup();
    render(
      <AccountsSection
        accounts={[baseAccount, expenseAcc]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    const nameInput = screen.getByLabelText(/Filter accounts by name/);
    await user.type(nameInput, "*Cash");
    expect(screen.getByText("Petty Cash")).toBeInTheDocument();
    expect(screen.queryByText("Repairs Expense")).not.toBeInTheDocument();
    await user.clear(nameInput);
    expect(screen.getByText("Repairs Expense")).toBeInTheDocument();
  });

  it("restricts rows by type selection; clear shows all again", async () => {
    const expenseAcc = {
      ...baseAccount,
      id: 7,
      name: "Repairs",
      type: "expense" as const,
    };
    const user = userEvent.setup();
    render(
      <AccountsSection
        accounts={[baseAccount, expenseAcc]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Filter accounts by type" }));
    await user.click(screen.getByRole("checkbox", { name: "expense" }));
    expect(screen.queryByText("Petty Cash")).not.toBeInTheDocument();
    expect(screen.getByText("Repairs")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByText("Petty Cash")).toBeInTheDocument();
    expect(screen.getByText("Repairs")).toBeInTheDocument();
  });

  it("combines filters with AND semantics", async () => {
    const expenseInactive = {
      ...inactiveAccount,
      id: 8,
      name: "Dead Expense",
      type: "expense" as const,
    };
    const expenseActive = {
      ...baseAccount,
      id: 9,
      name: "Live Expense",
      type: "expense" as const,
    };
    const user = userEvent.setup();
    render(
      <AccountsSection
        accounts={[baseAccount, expenseActive, expenseInactive]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    await user.selectOptions(screen.getByLabelText("Filter accounts by active status"), "all");
    await user.type(screen.getByLabelText(/Filter accounts by name/), "*Expense");
    await user.click(screen.getByRole("button", { name: "Filter accounts by type" }));
    await user.click(screen.getByRole("checkbox", { name: "expense" }));
    expect(screen.getByText("Live Expense")).toBeInTheDocument();
    expect(screen.getByText("Dead Expense")).toBeInTheDocument();
    expect(screen.queryByText("Petty Cash")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Filter accounts by active status"), "active");
    expect(screen.getByText("Live Expense")).toBeInTheDocument();
    expect(screen.queryByText("Dead Expense")).not.toBeInTheDocument();
  });

  it("shows no-match message when filters exclude all accounts", async () => {
    const user = userEvent.setup();
    render(
      <AccountsSection
        accounts={[baseAccount]}
        loading={false}
        error={null}
        onAccountCreated={vi.fn()}
        onAccountUpdated={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/Filter accounts by name/), "zzznomatch");
    expect(screen.getByText("No accounts match these filters.")).toBeInTheDocument();
    expect(screen.queryByText("Petty Cash")).not.toBeInTheDocument();
  });
});
