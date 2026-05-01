import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CelRuleSetsSection } from "./CelRuleSetsSection";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetchListAndCreate() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/import-rules/cel/rule-sets") && init?.method === "POST") {
      const body = JSON.parse(init.body as string) as { name: string };
      return new Response(
        JSON.stringify({
          id: 42,
          name: body.name,
          rule_set: { rules: [] },
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        }),
        { status: 201 },
      );
    }
    if (url.endsWith("/import-rules/cel/rule-sets") || url.match(/\/import-rules\/cel\/rule-sets\?/)) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    return new Response(`unmocked ${url}`, { status: 500 });
  });
}

describe("CelRuleSetsSection", () => {
  it("loads rule set list", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/import-rules/cel/rule-sets")) {
        return new Response(
          JSON.stringify([{ id: 1, name: "Bank A", updated_at: "2026-04-01T00:00:00Z" }]),
          { status: 200 },
        );
      }
      return new Response("x", { status: 500 });
    });

    render(<CelRuleSetsSection />);

    expect(await screen.findByRole("option", { name: "Bank A" })).toBeInTheDocument();
  });

  it("creates a new rule set after name and save", async () => {
    const fetchMock = mockFetchListAndCreate();
    render(<CelRuleSetsSection />);

    await userEvent.selectOptions(await screen.findByRole("combobox"), "New rule set…");
    await userEvent.type(screen.getByRole("textbox", { name: /^Rule set name$/i }), "My rules");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
      expect(posts.length).toBeGreaterThanOrEqual(1);
    });
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post).toBeTruthy();
    const body = JSON.parse((post![1] as RequestInit).body as string);
    expect(body.name).toBe("My rules");
    expect(body.rule_set.rules).toEqual([]);
  });

  it("revert resets draft after edit", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/import-rules/cel/rule-sets/1") && !init?.method) {
        return new Response(
          JSON.stringify({
            id: 1,
            name: "Original",
            rule_set: {
              rules: [
                {
                  id: null,
                  name: "R1",
                  enabled: true,
                  sort_order: 0,
                  expression: "null",
                  captures: [],
                },
              ],
            },
            created_at: "2026-04-01T00:00:00Z",
            updated_at: "2026-04-01T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/import-rules/cel/rule-sets")) {
        return new Response(
          JSON.stringify([{ id: 1, name: "Original", updated_at: "2026-04-01T00:00:00Z" }]),
          { status: 200 },
        );
      }
      return new Response("x", { status: 500 });
    });

    render(<CelRuleSetsSection />);
    await userEvent.selectOptions(await screen.findByRole("combobox"), "Original");

    const nameField = await screen.findByRole("textbox", { name: /^Rule set name$/i });
    await waitFor(() => {
      expect(nameField).toHaveValue("Original");
    });

    await userEvent.clear(nameField);
    await userEvent.type(nameField, "Changed");

    expect(screen.getByRole("button", { name: "Revert" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Revert" }));

    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /^Rule set name$/i })).toHaveValue("Original");
    });
  });
});
