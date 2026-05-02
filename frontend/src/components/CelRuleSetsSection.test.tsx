import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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

  it("moves a rule up when Up is clicked (order not undone by renumber)", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/import-rules/cel/rule-sets/1") && !init?.method) {
        return new Response(
          JSON.stringify({
            id: 1,
            name: "Two rules",
            rule_set: {
              rules: [
                { name: "Alpha", enabled: true, sort_order: 0, expression: "null", captures: [] },
                { name: "Beta", enabled: true, sort_order: 1, expression: "null", captures: [] },
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
          JSON.stringify([{ id: 1, name: "Two rules", updated_at: "2026-04-01T00:00:00Z" }]),
          { status: 200 },
        );
      }
      return new Response("x", { status: 500 });
    });

    render(<CelRuleSetsSection />);
    await userEvent.selectOptions(await screen.findByRole("combobox"), "Two rules");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Alpha/ })).toBeInTheDocument();
    });

    let items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText("Alpha")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Beta")).toBeInTheDocument();

    await userEvent.click(within(items[1]!).getAllByRole("button")[0]!);

    const upBeta = within(items[1]!).getByRole("button", { name: "Up" });
    await userEvent.click(upBeta);

    items = screen.getAllByRole("listitem");
    expect(within(items[0]!).getByText("Beta")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Alpha")).toBeInTheDocument();
  });
});
