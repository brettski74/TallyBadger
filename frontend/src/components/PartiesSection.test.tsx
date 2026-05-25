import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import type { Party } from "../api/parties";
import { PartiesSection } from "./PartiesSection";

afterEach(() => {
  vi.restoreAllMocks();
});

const sampleParty: Party = {
  id: 1,
  name: "Acme Yard Maintenance",
  role: "customer",
  is_active: true,
  match_patterns: [],
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

const tenantParty: Party = {
  id: 2,
  name: "Ridge Unit A",
  role: "customer",
  is_active: true,
  subtype: "Tenant",
  match_patterns: [],
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

const inactiveParty: Party = {
  id: 3,
  name: "Old Vendor LLC",
  role: "vendor",
  is_active: false,
  match_patterns: [],
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

const emptyAccounts: Account[] = [];

function mockPartiesFetch(
  registerRows: Party[] = [],
  extra?: (url: string, init?: RequestInit) => Response | undefined,
) {
  return vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("subtype-suggestions")) {
      return new Response(JSON.stringify(["Tenant", "Utilities"]), { status: 200 });
    }
    const custom = extra?.(url, init);
    if (custom) {
      return custom;
    }
    if (url.includes("/parties") && !url.includes("/parties/")) {
      const parsed = new URL(url, "http://test");
      if (parsed.searchParams.has("name") && parsed.searchParams.get("name") === "[bad") {
        return new Response(JSON.stringify({ detail: "name is not a valid regular expression" }), {
          status: 422,
        });
      }
      const activeParam = parsed.searchParams.get("is_active");
      if (activeParam === "true") {
        return new Response(JSON.stringify(registerRows.filter((p) => p.is_active)), { status: 200 });
      }
      if (activeParam === "false") {
        return new Response(JSON.stringify(registerRows.filter((p) => !p.is_active)), { status: 200 });
      }
      return new Response(JSON.stringify(registerRows), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  });
}

describe("PartiesSection", () => {
  it("fetches register with default active filter and lists rows", async () => {
    const fetchSpy = mockPartiesFetch([sampleParty, inactiveParty]);

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Acme Yard Maintenance")).toBeInTheDocument();
    });
    expect(screen.queryByText("Old Vendor LLC")).not.toBeInTheDocument();

    const registerCalls = fetchSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u.includes("/parties") && !u.includes("subtype"));
    expect(registerCalls.some((u) => u.includes("is_active=true"))).toBe(true);
  });

  it("opens role and subtype filter dropdowns with options from the API", async () => {
    mockPartiesFetch([tenantParty]);

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Ridge Unit A")).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Filter parties by role" }));

    const roleMenu = await screen.findByRole("listbox", { name: "Filter parties by role" });
    expect(within(roleMenu).getByLabelText("customer")).toBeInTheDocument();
    expect(within(roleMenu).getByLabelText("vendor")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Filter parties by subtype" }));

    const subtypeMenu = await screen.findByRole("listbox", { name: "Filter parties by subtype" });
    expect(within(subtypeMenu).getByLabelText("(no subtype)")).toBeInTheDocument();
    expect(within(subtypeMenu).getByLabelText("Tenant")).toBeInTheDocument();
    expect(within(subtypeMenu).getByLabelText("Utilities")).toBeInTheDocument();
  });

  it("surfaces 422 regex errors on the filter row", async () => {
    mockPartiesFetch([]);

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("Filter parties by name")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Filter parties by name"), {
      target: { value: "[bad" },
    });

    await waitFor(() => {
      expect(screen.getByText(/not a valid regular expression/i)).toBeInTheDocument();
    });
  });

  it("opens create modal and creates a party", async () => {
    const onPartyCreated = vi.fn();
    mockPartiesFetch([], (url, init) => {
      if (url.endsWith("/parties") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        expect(body.is_active).toBe(true);
        expect(body).not.toHaveProperty("is_active", false);
        return new Response(
          JSON.stringify({
            id: 2,
            name: "Vendor Co",
            role: "vendor",
            is_active: true,
            match_patterns: [],
            created_at: "2026-04-01T00:00:00Z",
            updated_at: "2026-04-01T00:00:00Z",
          }),
          { status: 201 },
        );
      }
      return undefined;
    });

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={onPartyCreated} onPartyUpdated={vi.fn()} />,
    );

    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /new party/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /new party/i }));
    await user.type(screen.getByLabelText("Party name"), "Vendor Co");
    await user.selectOptions(screen.getByLabelText("Party role"), "vendor");
    await user.click(screen.getByRole("button", { name: /create party/i }));

    await waitFor(() => {
      expect(onPartyCreated).toHaveBeenCalledWith(
        expect.objectContaining({ id: 2, name: "Vendor Co", role: "vendor" }),
      );
    });
  });

  it("updates a party from the edit modal", async () => {
    const onPartyUpdated = vi.fn();
    mockPartiesFetch([sampleParty], (url, init) => {
      if (url.endsWith("/parties/1") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        expect(body).not.toHaveProperty("is_active");
        return new Response(
          JSON.stringify({
            ...sampleParty,
            name: "Acme Yard Maintenance (updated)",
            role: "both",
          }),
          { status: 200 },
        );
      }
      return undefined;
    });

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={onPartyUpdated} />,
    );

    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Acme Yard Maintenance")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /edit party acme yard maintenance/i }));
    await user.clear(screen.getByLabelText("Edit party name"));
    await user.type(screen.getByLabelText("Edit party name"), "Acme Yard Maintenance (updated)");
    await user.selectOptions(screen.getByLabelText("Edit party role"), "both");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1, name: "Acme Yard Maintenance (updated)", role: "both" }),
      );
    });
  });

  it("saves the edit form when Ctrl+S is pressed inside the edit modal", async () => {
    const onPartyUpdated = vi.fn();
    mockPartiesFetch([sampleParty], (url, init) => {
      if (url.endsWith("/parties/1") && init?.method === "PATCH") {
        return new Response(JSON.stringify({ ...sampleParty, name: "Saved via keyboard" }), {
          status: 200,
        });
      }
      return undefined;
    });

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={onPartyUpdated} />,
    );

    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Acme Yard Maintenance")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /edit party acme yard maintenance/i }));
    const nameInput = screen.getByLabelText("Edit party name");
    nameInput.focus();
    fireEvent.keyDown(nameInput, { key: "s", code: "KeyS", ctrlKey: true, bubbles: true });

    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(expect.objectContaining({ name: "Saved via keyboard" }));
    });
  });

  it("opens new party modal on Ctrl+Shift+N when no modal is open", async () => {
    mockPartiesFetch([]);

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Parties" })).toBeInTheDocument();
    });

    fireEvent.keyDown(document, { key: "N", code: "KeyN", ctrlKey: true, shiftKey: true, bubbles: true });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Create party" })).toBeInTheDocument();
    });
  });

  it("does not PATCH deactivate when confirmation is declined", async () => {
    const onPartyUpdated = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchSpy = mockPartiesFetch([sampleParty]);

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={onPartyUpdated} />,
    );

    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Acme Yard Maintenance")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /deactivate party acme yard maintenance/i }));

    expect(confirmSpy).toHaveBeenCalled();
    const patchCalls = fetchSpy.mock.calls.filter(
      (c) => String(c[0]).includes("/parties/1") && c[1]?.method === "PATCH",
    );
    expect(patchCalls).toHaveLength(0);
    expect(onPartyUpdated).not.toHaveBeenCalled();
  });

  it("PATCHes deactivate after confirmation", async () => {
    const onPartyUpdated = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockPartiesFetch([sampleParty], (url, init) => {
      if (url.endsWith("/parties/1") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        expect(body).toEqual({ is_active: false });
        return new Response(JSON.stringify({ ...sampleParty, is_active: false }), { status: 200 });
      }
      return undefined;
    });

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={onPartyUpdated} />,
    );

    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Acme Yard Maintenance")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /deactivate party acme yard maintenance/i }));

    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(expect.objectContaining({ id: 1, is_active: false }));
    });
  });

  it("reactivates an inactive party and shows view for inactive rows", async () => {
    const onPartyUpdated = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm");
    mockPartiesFetch([inactiveParty], (url, init) => {
      if (url.endsWith("/parties/3") && init?.method === "PATCH") {
        return new Response(JSON.stringify({ ...inactiveParty, is_active: true }), { status: 200 });
      }
      return undefined;
    });

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={onPartyUpdated} />,
    );

    await waitFor(() => {
      expect(screen.queryByText("Old Vendor LLC")).not.toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter parties by active status"), "inactive");

    await waitFor(() => {
      expect(screen.getByText("Old Vendor LLC")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /view party old vendor llc/i }));
    expect(screen.getByRole("heading", { name: "View party" })).toBeInTheDocument();
    const viewDialog = screen.getByRole("dialog", { name: /view party/i });
    expect(within(viewDialog).getByLabelText("Party name")).toHaveAttribute("readOnly");

    const closeButtons = within(viewDialog).getAllByRole("button", { name: "Close" });
    await user.click(closeButtons[0]);
    await user.click(screen.getByRole("button", { name: /reactivate party old vendor llc/i }));

    expect(confirmSpy).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(expect.objectContaining({ id: 3, is_active: true }));
    });
  });

  it("subtype combobox loads suggestions in create modal", async () => {
    mockPartiesFetch([], (url, init) => {
      if (url.endsWith("/parties") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            id: 2,
            name: "X",
            role: "other",
            is_active: true,
            match_patterns: [],
            created_at: "2026-04-01T00:00:00Z",
            updated_at: "2026-04-01T00:00:00Z",
          }),
          { status: 201 },
        );
      }
      return undefined;
    });

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={vi.fn()} />,
    );

    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /new party/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /new party/i }));

    const subtype = screen.getByRole("textbox", { name: "Party subtype" });
    await user.type(subtype, "Ten");
    expect(document.querySelector(".subtype-ghost-suffix")).toHaveTextContent("ant");
    await user.keyboard("{Enter}");
    expect(subtype).toHaveValue("Tenant");
  });

  it("subtype ghost uses subtypes from register rows when suggestions API is empty", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/parties") && !url.includes("/parties/")) {
        return new Response(JSON.stringify([tenantParty]), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });

    render(
      <PartiesSection accounts={emptyAccounts} onPartyCreated={vi.fn()} onPartyUpdated={vi.fn()} />,
    );

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /new party/i }));
    const subtype = await screen.findByRole("textbox", { name: "Party subtype" });
    await user.type(subtype, "Te");
    expect(document.querySelector(".subtype-ghost-suffix")).toHaveTextContent("nant");
  });
});
