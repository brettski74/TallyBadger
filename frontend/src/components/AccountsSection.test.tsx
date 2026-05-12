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
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.clear(screen.getByLabelText("Edit name for account 5"));
    await user.type(screen.getByLabelText("Edit name for account 5"), "Spare Cash");
    await user.click(screen.getByRole("button", { name: "Save" }));

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
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.clear(screen.getByLabelText("Edit name for account 5"));
    await user.type(screen.getByLabelText("Edit name for account 5"), "Spare Cash");
    await user.selectOptions(screen.getByLabelText("Edit type for account 5"), "liability");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(patched).toBe(true);
    expect(onAccountUpdated).toHaveBeenCalledWith(updated);
  });
});
