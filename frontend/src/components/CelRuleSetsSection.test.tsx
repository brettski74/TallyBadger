import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it("selects the newly added rule for editing (not the first rule)", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/import-rules/cel/rule-sets/1") && !init?.method) {
        return new Response(
          JSON.stringify({
            id: 1,
            name: "One rule",
            rule_set: {
              rules: [
                {
                  name: "Existing",
                  enabled: true,
                  sort_order: 0,
                  expression: "true",
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
          JSON.stringify([{ id: 1, name: "One rule", updated_at: "2026-04-01T00:00:00Z" }]),
          { status: 200 },
        );
      }
      return new Response("x", { status: 500 });
    });

    render(<CelRuleSetsSection />);
    await userEvent.selectOptions(await screen.findByRole("combobox"), "One rule");

    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /^CEL expression$/i })).toHaveValue("true");
    });

    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).not.toHaveClass("is-active");
    expect(items[1]).toHaveClass("is-active");
    expect(screen.getByRole("textbox", { name: /^CEL expression$/i })).toHaveValue("null");
  });

  it("moves a rule up when Move rule up is clicked (order not undone by renumber)", async () => {
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

    const upBeta = within(items[1]!).getByRole("button", { name: "Move rule up" });
    await userEvent.click(upBeta);

    items = screen.getAllByRole("listitem");
    expect(within(items[0]!).getByText("Beta")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Alpha")).toBeInTheDocument();
  });

  it("exposes Save keyboard hint on the Save button when dirty", async () => {
    mockFetchListAndCreate();
    render(<CelRuleSetsSection />);

    await userEvent.selectOptions(await screen.findByRole("combobox"), "New rule set…");
    await userEvent.type(screen.getByRole("textbox", { name: /^Rule set name$/i }), "x");

    const saveBtn = screen.getByRole("button", { name: "Save" });
    expect(saveBtn).toHaveAttribute("title", expect.stringMatching(/Save \(Ctrl\+S\)|Save \(⌘\+S\)/));
    expect(saveBtn).toHaveAttribute("aria-keyshortcuts", expect.stringMatching(/Control|Meta/));
  });

  it("maps 422 validation errors to inline error-text under rule row and fields", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/import-rules/cel/rule-sets") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            detail: {
              message: "Rule set validation failed",
              errors: [
                {
                  rule_index: 0,
                  rule_label: "rule[0]",
                  field: "expression",
                  message: "syntax error in CEL",
                },
                {
                  rule_index: 0,
                  rule_label: "rule[0]",
                  field: "pattern",
                  message: "unclosed bracket",
                  capture_index: 0,
                  matcher_label: "description",
                },
              ],
            },
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/import-rules/cel/rule-sets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("x", { status: 500 });
    });

    render(<CelRuleSetsSection />);
    await userEvent.selectOptions(await screen.findByRole("combobox"), "New rule set…");
    await userEvent.type(screen.getByRole("textbox", { name: /^Rule set name$/i }), "Bad");
    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));
    await userEvent.click(screen.getByRole("button", { name: "Add matcher" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const alerts = screen.getAllByRole("alert");
      const texts = alerts.map((el) => el.textContent);
      expect(texts.filter((t) => t?.includes("syntax error in CEL"))).toHaveLength(2);
      expect(texts.filter((t) => t?.includes("unclosed bracket"))).toHaveLength(2);
    });
    for (const el of screen.getAllByRole("alert")) {
      if (el.textContent?.includes("syntax error") || el.textContent?.includes("unclosed")) {
        expect(el).toHaveClass("error-text");
      }
    }
  });

  it("submits when Ctrl+S is pressed while focus is inside the form", async () => {
    const fetchMock = mockFetchListAndCreate();
    render(<CelRuleSetsSection />);

    await userEvent.selectOptions(await screen.findByRole("combobox"), "New rule set…");
    const nameField = screen.getByRole("textbox", { name: /^Rule set name$/i });
    await userEvent.type(nameField, "Hotkey rules");
    fireEvent.keyDown(nameField, { key: "s", ctrlKey: true, bubbles: true });

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
      expect(posts.length).toBeGreaterThanOrEqual(1);
    });
  });
});
