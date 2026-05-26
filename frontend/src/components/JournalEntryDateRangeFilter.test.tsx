import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { JournalEntryDateRangeFilter } from "./JournalEntryDateRangeFilter";
import { matchQuickRangeId } from "../lib/journalEntryDateRangeCatalog";

afterEach(() => {
  vi.restoreAllMocks();
});

function ControlledFilter({
  initial = { fromDate: "", toDate: "" },
}: {
  initial?: { fromDate: string; toDate: string };
}) {
  const [value, setValue] = useState(initial);
  return (
    <JournalEntryDateRangeFilter
      value={value}
      onChange={(patch) => setValue((prev) => ({ ...prev, ...patch }))}
    />
  );
}

describe("journalEntryDateRangeCatalog", () => {
  it("matches catalogue expressions exactly after trim", () => {
    expect(matchQuickRangeId("  now/y ", " now ")).toBe("ytd");
    expect(matchQuickRangeId("now/y", "now-1d")).toBe("custom");
    expect(matchQuickRangeId("", "now")).toBe("custom");
  });
});

describe("JournalEntryDateRangeFilter", () => {
  it("selecting a quick range writes catalogue expressions", async () => {
    const user = userEvent.setup();
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/date-range/resolve")) {
        return new Response(JSON.stringify({ date: "2026-05-06" }), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(<ControlledFilter />);
    await user.selectOptions(screen.getByLabelText("Quick date range"), "mtd");

    const from = screen.getByLabelText("Filter from date");
    await user.click(from);
    expect((from as HTMLInputElement).value).toBe("now/M");
    const to = screen.getByLabelText("Filter to date");
    await user.click(to);
    expect((to as HTMLInputElement).value).toBe("now");
  });

  it("reverse-matches quick range when both fields are blurred", async () => {
    const user = userEvent.setup();
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/date-range/resolve")) {
        return new Response(JSON.stringify({ date: "2026-01-01" }), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(<ControlledFilter initial={{ fromDate: "now/y", toDate: "now" }} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Quick date range")).toHaveValue("ytd");
    });

    const from = screen.getByLabelText("Filter from date");
    await user.click(from);
    await user.clear(from);
    await user.type(from, "now-7d");
    expect(screen.getByLabelText("Quick date range")).toHaveValue("ytd");

    await user.tab();
    await user.tab();

    await waitFor(() => {
      expect(screen.getByLabelText("Quick date range")).toHaveValue("last-7-days");
    });
  });

  it("does not reverse-match while a date field is focused", async () => {
    const user = userEvent.setup();
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/date-range/resolve")) {
        return new Response(JSON.stringify({ date: "2026-05-06" }), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(<ControlledFilter initial={{ fromDate: "now/y", toDate: "now" }} />);
    await waitFor(() => {
      expect(screen.getByLabelText("Quick date range")).toHaveValue("ytd");
    });

    const from = screen.getByLabelText("Filter from date");
    await user.click(from);
    await user.clear(from);
    await user.type(from, "now-7d");

    expect(screen.getByLabelText("Quick date range")).toHaveValue("ytd");
    expect((from as HTMLInputElement).value).toBe("now-7d");
  });

  it("shows resolved calendar date when blurred", async () => {
    const user = userEvent.setup();
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("expr=2026-01-15")) {
        return new Response(JSON.stringify({ date: "2026-01-15" }), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(<ControlledFilter />);
    const from = screen.getByLabelText("Filter from date");
    await user.click(from);
    await user.type(from, "2026-01-15");
    await user.tab();

    await waitFor(() => {
      expect((from as HTMLInputElement).value).toBe("15/01/2026");
    });
  });

  it("shows custom when resolve fails", async () => {
    const user = userEvent.setup();
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/date-range/resolve")) {
        return new Response(JSON.stringify({ detail: "bad expr" }), { status: 422 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(<ControlledFilter initial={{ fromDate: "bad", toDate: "now" }} />);
    await user.tab();

    await waitFor(() => {
      expect(screen.getAllByRole("alert")[0]).toHaveTextContent(/bad expr/i);
      expect(screen.getByLabelText("Quick date range")).toHaveValue("custom");
    });
  });
});
