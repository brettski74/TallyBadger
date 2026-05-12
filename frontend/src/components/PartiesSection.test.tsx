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

describe("PartiesSection", () => {
  it("lists parties from props", () => {
    vi.spyOn(global, "fetch").mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[sampleParty]}
        loading={false}
        error={null}
        onPartyCreated={vi.fn()}
        onPartyUpdated={vi.fn()}
      />,
    );

    const table = screen.getByRole("table");
    expect(within(table).getByText("Acme Yard Maintenance")).toBeInTheDocument();
    expect(within(table).getByText("customer")).toBeInTheDocument();
  });

  it("creates a party and notifies parent", async () => {
    const onPartyCreated = vi.fn();
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
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
    });

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[]}
        loading={false}
        error={null}
        onPartyCreated={onPartyCreated}
        onPartyUpdated={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Party name"), "Vendor Co");
    await user.selectOptions(screen.getByLabelText("Party role"), "vendor");
    await user.click(screen.getByRole("button", { name: "Create party" }));

    await waitFor(() => {
      expect(onPartyCreated).toHaveBeenCalledWith(
        expect.objectContaining({ id: 2, name: "Vendor Co", role: "vendor" }),
      );
    });
  });

  it("updates a party after edit save", async () => {
    const onPartyUpdated = vi.fn();
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response(
        JSON.stringify({
          ...sampleParty,
          name: "Acme Yard Maintenance (updated)",
          role: "both",
        }),
        { status: 200 },
      );
    });

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[sampleParty]}
        loading={false}
        error={null}
        onPartyCreated={vi.fn()}
        onPartyUpdated={onPartyUpdated}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /edit party acme yard maintenance/i }));
    await user.clear(screen.getByLabelText("Edit party name"));
    await user.type(screen.getByLabelText("Edit party name"), "Acme Yard Maintenance (updated)");
    await user.selectOptions(screen.getByLabelText("Edit party role"), "both");
    await user.click(screen.getByRole("button", { name: /save changes \(ctrl\+s\)/i }));

    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1, name: "Acme Yard Maintenance (updated)", role: "both" }),
      );
    });
  });

  it("saves the edit form when Ctrl+S is pressed while focus is inside the edit form", async () => {
    const onPartyUpdated = vi.fn();
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response(JSON.stringify({ ...sampleParty, name: "Saved via keyboard" }), { status: 200 });
    });

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[sampleParty]}
        loading={false}
        error={null}
        onPartyCreated={vi.fn()}
        onPartyUpdated={onPartyUpdated}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /edit party acme yard maintenance/i }));
    const nameInput = screen.getByLabelText("Edit party name");
    nameInput.focus();
    fireEvent.keyDown(nameInput, { key: "s", code: "KeyS", ctrlKey: true, bubbles: true });

    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(expect.objectContaining({ name: "Saved via keyboard" }));
    });
  });

  it("does not PATCH deactivate when confirmation is declined", async () => {
    const onPartyUpdated = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchSpy = vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[sampleParty]}
        loading={false}
        error={null}
        onPartyCreated={vi.fn()}
        onPartyUpdated={onPartyUpdated}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /deactivate party acme yard maintenance/i }));

    expect(confirmSpy).toHaveBeenCalled();
    const patchCalls = fetchSpy.mock.calls.filter((c) => String(c[0]).includes("/parties/1") && c[1]?.method === "PATCH");
    expect(patchCalls).toHaveLength(0);
    expect(onPartyUpdated).not.toHaveBeenCalled();
  });

  it("PATCHes deactivate after confirmation", async () => {
    const onPartyUpdated = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.endsWith("/parties/1") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        expect(body).toEqual({ is_active: false });
        return new Response(JSON.stringify({ ...sampleParty, is_active: false }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[sampleParty]}
        loading={false}
        error={null}
        onPartyCreated={vi.fn()}
        onPartyUpdated={onPartyUpdated}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /deactivate party acme yard maintenance/i }));

    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(expect.objectContaining({ id: 1, is_active: false }));
    });
  });

  it("reactivates an inactive party immediately without confirmation", async () => {
    const onPartyUpdated = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm");
    vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.endsWith("/parties/3") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        expect(body).toEqual({ is_active: true });
        return new Response(JSON.stringify({ ...inactiveParty, is_active: true }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[inactiveParty]}
        loading={false}
        error={null}
        onPartyCreated={vi.fn()}
        onPartyUpdated={onPartyUpdated}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /reactivate party old vendor llc/i }));

    expect(confirmSpy).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(expect.objectContaining({ id: 3, is_active: true }));
    });
  });

  it("subtype combobox loads suggestions and accepts one on Enter", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify(["Tenant", "Utilities"]), { status: 200 });
      }
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
    });

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[]}
        loading={false}
        error={null}
        onPartyCreated={vi.fn()}
        onPartyUpdated={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });
    const subtype = screen.getByRole("textbox", { name: "Party subtype" });
    await user.type(subtype, "Ten");
    expect(document.querySelector(".subtype-ghost-suffix")).toHaveTextContent("ant");
    await user.keyboard("{Enter}");
    expect(subtype).toHaveValue("Tenant");
  });

  it("subtype ghost uses subtypes from loaded parties when suggestions API returns empty", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("subtype-suggestions")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("{}", { status: 201 });
    });

    render(
      <PartiesSection
        accounts={emptyAccounts}
        parties={[tenantParty, sampleParty]}
        loading={false}
        error={null}
        onPartyCreated={vi.fn()}
        onPartyUpdated={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    const subtype = await screen.findByRole("textbox", { name: "Party subtype" });
    await user.type(subtype, "Te");
    expect(document.querySelector(".subtype-ghost-suffix")).toHaveTextContent("nant");
  });
});
