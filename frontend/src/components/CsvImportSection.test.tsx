import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import { CsvImportSection } from "./CsvImportSection";
import { readFileAsText } from "../lib/readFileAsText";

vi.mock("../lib/readFileAsText", () => ({
  readFileAsText: vi.fn(),
}));

const TEMPLATE_API_DEFAULTS = {
  default_import_account_id: null,
  default_import_normal_balance: null,
} as const;

const EMPTY_ACCOUNTS: Account[] = [];

const SAMPLE_ACCOUNTS: Account[] = [
  { id: 1, name: "Cash", type: "asset", is_active: true, created_at: "2026-04-01T00:00:00Z", updated_at: "2026-04-01T00:00:00Z" },
  { id: 2, name: "Loans Payable", type: "liability", is_active: true, created_at: "2026-04-01T00:00:00Z", updated_at: "2026-04-01T00:00:00Z" },
];

function mockListEndpoints() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/import-templates") && init?.method === "POST") {
      return new Response(
        JSON.stringify({
          id: 1,
          name: "My tpl",
          has_header_row: true,
          columns: [
            { attribute_name: "posted_on", data_type: "date", date_format: "YYYY-MM-DD" },
            { attribute_name: "amount", data_type: "numeric", date_format: null },
          ],
          cel_rule_set_id: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
          ...TEMPLATE_API_DEFAULTS,
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
            { attribute_name: "posted_on", data_type: "date", date_format: "YYYY-MM-DD" },
            { attribute_name: "amount", data_type: "numeric", date_format: null },
          ],
          cel_rule_set_id: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
          ...TEMPLATE_API_DEFAULTS,
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
    if (url.includes("/imports/csv/execute") && init?.method === "POST") {
      return new Response(JSON.stringify({ posted_entries: 1, dropped_rows: 0, row_errors: [], entries: [] }), {
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

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} />);

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

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} />);
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

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} />);
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

  it("sets default import normal balance from selected account type", async () => {
    mockListEndpoints();
    vi.mocked(readFileAsText).mockResolvedValue("a,b\n1,2\n");

    render(<CsvImportSection accounts={SAMPLE_ACCOUNTS} />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "t.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await userEvent.selectOptions(screen.getByLabelText("Default import account"), "1");
    expect(screen.getByLabelText("Default import account normal balance")).toHaveValue("debit");

    await userEvent.selectOptions(screen.getByLabelText("Default import account"), "2");
    expect(screen.getByLabelText("Default import account normal balance")).toHaveValue("credit");
  });

  it("disables save when template name is blank", async () => {
    mockListEndpoints();
    vi.mocked(readFileAsText).mockResolvedValue("a,b\n1,2\n");

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "t.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await screen.findByLabelText("Template name");
    expect(screen.getByRole("button", { name: "Save template" })).toBeDisabled();
  });

  it("fills blank attribute names from header row when header is enabled", async () => {
    mockListEndpoints();
    vi.mocked(readFileAsText).mockResolvedValue("posted_on,amount,memo\n2024-01-01,12.34,hello\n");

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "t.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await userEvent.type(screen.getByLabelText("Attribute for column 2"), "manual_amount");
    await userEvent.click(screen.getByLabelText("First row is a header"));

    expect(screen.getByLabelText("Attribute for column 1")).toHaveValue("posted_on");
    expect(screen.getByLabelText("Attribute for column 2")).toHaveValue("manual_amount");
    expect(screen.getByLabelText("Attribute for column 3")).toHaveValue("memo");
  });

  it("saves a new template when name is provided", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/import-templates") && init?.method === "POST") {
        const payload = JSON.parse(String(init.body));
        expect(payload.columns[0].date_format).toBe("YYYY-MM-DD");
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
            ...TEMPLATE_API_DEFAULTS,
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
            ...TEMPLATE_API_DEFAULTS,
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

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "t.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await userEvent.type(screen.getByLabelText("Attribute for column 1"), "x");
    await userEvent.selectOptions(screen.getByLabelText("Type for column 1"), "date");
    await userEvent.type(screen.getByLabelText("Date format for column 1"), "YYYY-MM-DD");
    await userEvent.type(screen.getByLabelText("Template name"), "My tpl");
    await userEvent.click(screen.getByRole("button", { name: "Save template" }));

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(([, init]) => init && init.method === "POST");
      expect(posts.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("executes import from preview", async () => {
    const fetchMock = mockListEndpoints();
    vi.mocked(readFileAsText).mockResolvedValue("date,summary,dr,cr,amount\n2026-07-01,Rent July,Cash,Rent Revenue,1200\n");

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "import.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await userEvent.type(screen.getByLabelText("Attribute for column 1"), "date");
    await userEvent.selectOptions(screen.getByLabelText("Type for column 1"), "date");
    await userEvent.type(screen.getByLabelText("Date format for column 1"), "YYYY-MM-DD");
    await userEvent.type(screen.getByLabelText("Attribute for column 2"), "summary");
    await userEvent.type(screen.getByLabelText("Attribute for column 3"), "dr-account");
    await userEvent.type(screen.getByLabelText("Attribute for column 4"), "cr-account");
    await userEvent.type(screen.getByLabelText("Attribute for column 5"), "amount");
    await userEvent.selectOptions(screen.getByLabelText("Type for column 5"), "numeric");

    await userEvent.click(screen.getByRole("button", { name: "Execute import" }));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Import complete: 1 entries posted");
    });
    const executeCall = fetchMock.mock.calls.find(
      ([input, init]) => (typeof input === "string" ? input : input.toString()).includes("/imports/csv/execute") && init?.method === "POST",
    );
    expect(executeCall).toBeTruthy();
  });

  it("lists every row error when execute returns 422 with row_errors", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/imports/csv/execute") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            detail: {
              message: "Validation failed",
              row_errors: [
                { row_number: 4, errors: ["bad date on row 4"] },
                { row_number: 2, errors: ["bad amount"] },
              ],
            },
          }),
          { status: 422 },
        );
      }
      if (url.endsWith("/import-templates") || url.match(/\/import-templates\?/)) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/import-rules/cel/rule-sets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("unmocked", { status: 500 });
    });

    vi.mocked(readFileAsText).mockResolvedValue("a,b\n1,2\n3,4\n");

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "t.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await userEvent.type(screen.getByLabelText("Attribute for column 1"), "x");
    await userEvent.type(screen.getByLabelText("Attribute for column 2"), "y");

    await userEvent.click(screen.getByRole("button", { name: "Execute import" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("2 rows with errors");
    expect(alert).toHaveTextContent("Row 2:");
    expect(alert).toHaveTextContent("bad amount");
    expect(alert).toHaveTextContent("Row 4:");
    expect(alert).toHaveTextContent("bad date on row 4");

    const items = alert.querySelectorAll(".csv-import-validation-rows li");
    expect(items[0]).toHaveTextContent("Row 2:");
    expect(items[1]).toHaveTextContent("Row 4:");
  });

  it("calls onImportSucceeded after successful execute", async () => {
    mockListEndpoints();
    vi.mocked(readFileAsText).mockResolvedValue("date,summary,dr,cr,amount\n2026-07-01,Rent July,Cash,Rent Revenue,1200\n");
    const onImportSucceeded = vi.fn();

    render(<CsvImportSection accounts={EMPTY_ACCOUNTS} onImportSucceeded={onImportSucceeded} />);
    await screen.findByLabelText("CSV file");
    const file = new File(["dummy"], "import.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("CSV file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Continue to preview" }));

    await userEvent.type(screen.getByLabelText("Attribute for column 1"), "date");
    await userEvent.selectOptions(screen.getByLabelText("Type for column 1"), "date");
    await userEvent.type(screen.getByLabelText("Date format for column 1"), "YYYY-MM-DD");
    await userEvent.type(screen.getByLabelText("Attribute for column 2"), "summary");
    await userEvent.type(screen.getByLabelText("Attribute for column 3"), "dr-account");
    await userEvent.type(screen.getByLabelText("Attribute for column 4"), "cr-account");
    await userEvent.type(screen.getByLabelText("Attribute for column 5"), "amount");
    await userEvent.selectOptions(screen.getByLabelText("Type for column 5"), "numeric");

    await userEvent.click(screen.getByRole("button", { name: "Execute import" }));

    await waitFor(() => {
      expect(onImportSucceeded).toHaveBeenCalledTimes(1);
    });
  });
});
