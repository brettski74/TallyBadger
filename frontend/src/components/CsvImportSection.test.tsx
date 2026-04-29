import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CsvImportSection } from "./CsvImportSection";
import { readFileAsText } from "../lib/readFileAsText";

vi.mock("../lib/readFileAsText", () => ({
  readFileAsText: vi.fn(),
}));

function mockListEndpoints() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/import-templates") && init?.method === "POST") {
      return new Response(
        JSON.stringify({
          id: 1,
          name: "My tpl",
          has_header_row: true,
          columns: [
            { attribute_name: "posted_on", data_type: "date", date_format: "%Y-%m-%d" },
            { attribute_name: "amount", data_type: "numeric", date_format: null },
          ],
          cel_rule_set_id: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        }),
        { status: 201 },
      );
    }
    if (url.includes("/import-templates/") && init?.method === undefined) {
      const id = url.split("/").pop();
      return new Response(
        JSON.stringify({
          id: Number(id),
          name: "Bank",
          has_header_row: true,
          columns: [
            { attribute_name: "posted_on", data_type: "date", date_format: "%Y-%m-%d" },
            { attribute_name: "amount", data_type: "numeric", date_format: null },
          ],
          cel_rule_set_id: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
        }),
        { status: 200 },
      );
    }
    if (url.endsWith("/import-templates") || url.match(/\/import-templates\?/)) {
      return new Response(
        JSON.stringify([{ id: 1, name: "Bank", updated_at: "2026-04-01T00:00:00Z" }]),
        { status: 200 },
      );
    }
    if (url.includes("/import-rules/cel/rule-sets")) {
      return new Response(JSON.stringify([{ id: 10, name: "rs1", updated_at: "2026-04-01T00:00:00Z" }]), {
        status: 200,
      });
    }
    return new Response(`unmocked: ${url}`, { status: 500 });
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CsvImportSection", () => {
  it("requires a file before continuing", async () => {
    mockListEndpoints();
    vi.mocked(readFileAsText).mockResolvedValue("");

    render(<CsvImportSection />);

    await screen.findByRole("heading", { name: "CSV import" });
    const form = screen.getByRole("button", { name: "Continue to preview" }).closest("form");
    expect(form).toBeTruthy();
    fireEvent.submit(form!);

    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a CSV file first.");
  });

  it("opens preview with defaults and respects preview row limit", async () => {
    mockListEndpoints();
    const body = "c1,c2\n" + Array.from({ length: 30 }, (_, i) => `${i},v`).join("\n");
    vi.mocked(readFileAsText).mockResolvedValue(body);

    render(<CsvImportSection />);
    await screen.findByLabelText("CSV file");

    const file = new File(["dummy"], "rows.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    expect(await screen.findByLabelText("First row is a header")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Preview row limit"), "10");
    expect(screen.getAllByRole("rowheader", { name: /^Row \d+$/ })).toHaveLength(10);

    await userEvent.selectOptions(screen.getByLabelText("Preview row limit"), "25");
    expect(screen.getAllByRole("rowheader", { name: /^Row \d+$/ })).toHaveLength(25);
  });

  it("applies a selected import template to column mapping", async () => {
    mockListEndpoints();
    vi.mocked(readFileAsText).mockResolvedValue("posted_on,amount,extra\n2024-01-01,12,note\n");

    render(<CsvImportSection />);
    await screen.findByLabelText("Import template");
    await userEvent.selectOptions(screen.getByLabelText("Import template"), "1");

    await waitFor(() => {
      expect(screen.queryByText("Loading template…")).not.toBeInTheDocument();
    });

    const file = new File(["dummy"], "bank.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    expect(await screen.findByLabelText("Attribute for column 1")).toHaveValue("posted_on");
    expect(screen.getByLabelText("Attribute for column 2")).toHaveValue("amount");
    expect(screen.getByLabelText("First row is a header")).toBeChecked();
  });

  it("disables save when template name is blank", async () => {
    mockListEndpoints();
    vi.mocked(readFileAsText).mockResolvedValue("a,b\n1,2\n");

    render(<CsvImportSection />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "t.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await screen.findByLabelText("Template name");
    expect(screen.getByRole("button", { name: "Save template" })).toBeDisabled();
  });

  it("saves a new template when name is provided", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/import-templates") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            id: 2,
            name: "My tpl",
            has_header_row: false,
            columns: [
              { attribute_name: "x", data_type: "string", date_format: null },
              { attribute_name: null, data_type: "string", date_format: null },
            ],
            cel_rule_set_id: null,
            created_at: "2026-04-01T00:00:00Z",
            updated_at: "2026-04-01T00:00:00Z",
          }),
          { status: 201 },
        );
      }
      if (url.includes("/import-templates/") && init?.method === undefined) {
        return new Response(
          JSON.stringify({
            id: 1,
            name: "Bank",
            has_header_row: true,
            columns: [],
            cel_rule_set_id: null,
            created_at: "2026-04-01T00:00:00Z",
            updated_at: "2026-04-01T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/import-templates")) {
        return new Response(JSON.stringify([{ id: 1, name: "Bank", updated_at: "2026-04-01T00:00:00Z" }]), {
          status: 200,
        });
      }
      if (url.includes("/import-rules/cel/rule-sets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("x", { status: 500 });
    });

    vi.mocked(readFileAsText).mockResolvedValue("a,b\n1,2\n");

    render(<CsvImportSection />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "t.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await userEvent.type(screen.getByLabelText("Attribute for column 1"), "x");
    await userEvent.type(screen.getByLabelText("Template name"), "My tpl");
    await userEvent.click(screen.getByRole("button", { name: "Save template" }));

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(([, init]) => init && init.method === "POST");
      expect(posts.length).toBeGreaterThanOrEqual(1);
    });
  });
});
