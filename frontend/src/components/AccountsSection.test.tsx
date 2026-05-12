import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await user.type(screen.getByLabelText("New account name"), "Repairs");
    await user.selectOptions(screen.getByLabelText("New account type"), "expense");
    await user.click(screen.getByRole("button", { name: /Save new account \(Ctrl\+S\)|Save new account \(⌘\+S\)/ }));

    expect(posted).toBe(true);
    expect(onAccountCreated).toHaveBeenCalledWith(created);
  });

  it("discard on inline create does not call fetch", async () => {
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
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await user.type(screen.getByLabelText("New account name"), "Draft");
    await user.click(screen.getByRole("button", { name: /Discard \(Ctrl\+Shift\+D\)|Discard \(⌘\+Shift\+D\)/ }));

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("New account name")).not.toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: /Reactivate account Petty Cash/ }));

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(patched).toBe(true);
    expect(onAccountUpdated).toHaveBeenCalledWith(updated);
  });
});
