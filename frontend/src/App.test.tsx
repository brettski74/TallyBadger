import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetchImplementation(handlers: Array<(input: RequestInfo | URL, init?: RequestInit) => Response>) {
  let call = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const handler = handlers[Math.min(call, handlers.length - 1)];
    call += 1;
    return handler(input, init);
  });
}

describe("App", () => {
  it("renders account list from API", async () => {
    mockFetchImplementation([
      () =>
        new Response(
          JSON.stringify([
            {
              id: 1,
              name: "Cash",
              type: "asset",
              is_active: true,
              created_at: "2026-04-01T00:00:00Z",
              updated_at: "2026-04-01T00:00:00Z",
            },
          ]),
          { status: 200 },
        ),
      () => new Response(JSON.stringify([]), { status: 200 }),
    ]);

    render(<App />);

    expect(await screen.findByText("Cash")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("creates an account successfully", async () => {
    mockFetchImplementation([
      () => new Response(JSON.stringify([]), { status: 200 }),
      () => new Response(JSON.stringify([]), { status: 200 }),
      (_input, init) => {
        expect(init?.method).toBe("POST");
        return new Response(
          JSON.stringify({
            id: 2,
            name: "Repairs Expense",
            type: "expense",
            is_active: true,
            created_at: "2026-04-01T00:00:00Z",
            updated_at: "2026-04-01T00:00:00Z",
          }),
          { status: 201 },
        );
      },
    ]);

    render(<App />);

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Account name"), "Repairs Expense");
    await user.selectOptions(screen.getByLabelText("Account type"), "expense");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Repairs Expense")).toBeInTheDocument();
  });

  it("shows duplicate-name API error", async () => {
    mockFetchImplementation([
      () => new Response(JSON.stringify([]), { status: 200 }),
      () => new Response(JSON.stringify([]), { status: 200 }),
      () => new Response(JSON.stringify({ detail: "account name already exists" }), { status: 409 }),
    ]);

    render(<App />);

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Account name"), "Cash");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("account name already exists");
    });
  });

  it("shows parties tab with loaded parties", async () => {
    mockFetchImplementation([
      () => new Response(JSON.stringify([]), { status: 200 }),
      () =>
        new Response(
          JSON.stringify([
            {
              id: 1,
              name: "Acme Yard Maintenance",
              role: "customer",
              is_active: true,
              created_at: "2026-04-01T00:00:00Z",
              updated_at: "2026-04-01T00:00:00Z",
            },
          ]),
          { status: 200 },
        ),
    ]);

    render(<App />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Parties" }));

    expect(await screen.findByRole("heading", { name: "Create party" })).toBeInTheDocument();
    expect(screen.getByText("Acme Yard Maintenance")).toBeInTheDocument();
  });

  it("shows accrual plans tab and loads plans list", async () => {
    mockFetchImplementation([
      () => new Response(JSON.stringify([]), { status: 200 }),
      () => new Response(JSON.stringify([]), { status: 200 }),
      () => new Response(JSON.stringify([]), { status: 200 }),
    ]);

    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Accrual plans" }));

    expect(await screen.findByRole("heading", { name: "Accrual plans" })).toBeInTheDocument();
  });
});
