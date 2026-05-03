import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.clear(screen.getByLabelText("Edit party name"));
    await user.type(screen.getByLabelText("Edit party name"), "Acme Yard Maintenance (updated)");
    await user.selectOptions(screen.getByLabelText("Edit party role"), "both");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(onPartyUpdated).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1, name: "Acme Yard Maintenance (updated)", role: "both" }),
      );
    });
  });
});
