import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account } from "../api/accounts";
import { JournalEntriesPanel } from "./JournalEntriesPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

const accounts: Account[] = [
  {
    id: 1,
    name: "Cash",
    type: "asset",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
  {
    id: 2,
    name: "Income",
    type: "revenue",
    is_active: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
];

const parties = [
  {
    id: 1,
    name: "Acme Yard Maintenance",
    role: "customer",
    is_active: true,
    match_patterns: [],
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
  },
];

describe("JournalEntriesPanel", () => {
  it("renders header columns in the order that matches body cells", async () => {
    const listPayload = [
      {
        id: 7,
        entry_date: "2026-04-10",
        summary: "Rent accrual",
        description: "Test",
        requires_review: true,
        cheque_id: null,
        created_at: "2026-04-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
        debit_side_label: "Cash",
        credit_side_label: "Income",
        party_labels: "Acme Yard Maintenance",
        amount: "25.00",
      },
    ];

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries")) {
        return new Response(JSON.stringify(listPayload), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    await screen.findByText("Rent accrual");

    const table = screen.getByRole("table");
    const headerRow = within(table).getAllByRole("row")[0];
    const headerLabels = within(headerRow)
      .getAllByRole("columnheader")
      .map((th) => th.textContent?.trim() ?? "");
    expect(headerLabels).toEqual([
      "Date",
      "Summary",
      "Needs review",
      "Parties",
      "Debit account",
      "Credit account",
      "Amount",
      "",
    ]);

    const bodyRows = within(table).getAllByRole("row").slice(1);
    const bodyCells = within(bodyRows[0]).getAllByRole("cell").map((td) => td.textContent?.trim() ?? "");
    expect(bodyCells.slice(0, 7)).toEqual([
      "2026-04-10",
      "Rent accrual",
      "Yes",
      "Acme Yard Maintenance",
      "Cash",
      "Income",
      "25.00",
    ]);
  });

  it("loads list and completes edit save path", async () => {
    const listPayload = [
      {
        id: 7,
        entry_date: "2026-04-10",
        summary: "Rent accrual",
        description: "Test",
        requires_review: false,
        cheque_id: null,
        created_at: "2026-04-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
        debit_side_label: "Cash",
        credit_side_label: "Income",
        party_labels: "Acme Yard Maintenance",
        amount: "25.00",
      },
    ];
    const entryPayload = {
      id: 7,
      entry_date: "2026-04-10",
      summary: "Rent accrual",
      description: "Test",
      requires_review: false,
      cheque_id: null,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
      review_messages: [],
      lines: [
        { id: 10, account_id: 1, party_id: 1, amount: "25.00", account_name: "Cash", party_name: "Acme Yard Maintenance" },
        { id: 11, account_id: 2, party_id: 1, amount: "-25.00", account_name: "Income", party_name: "Acme Yard Maintenance" },
      ],
    };

    vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries/7/attachments")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (/\/journal-entries\/7\/?$/.test(url)) {
        if (method === "PUT") {
          return new Response(
            JSON.stringify({ ...entryPayload, summary: "Updated summary", description: "Updated" }),
            { status: 200 },
          );
        }
        return new Response(JSON.stringify(entryPayload), { status: 200 });
      }
      if (url.includes("/journal-entries")) {
        return new Response(JSON.stringify(listPayload), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    expect(await screen.findByText("Rent accrual")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Edit journal entry: Rent accrual/ }));

    expect(await screen.findByRole("heading", { name: "Journal entry details" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Entry description"));
    await user.type(screen.getByLabelText("Entry description"), "Updated");

    await user.click(screen.getByRole("button", { name: /Save changes/ }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Journal entries" })).toBeInTheDocument();
    });
  });

  it("requests needs_review=true on list when filter checkbox is enabled", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const isPlainJournalEntriesListUrl = (u: unknown) => {
      const s = String(u);
      return (
        s.includes("/journal-entries")
        && !s.includes("/journal-entry-filter-presets")
        && !/\/journal-entries\/\d/.test(s)
      );
    };
    const firstListCall = fetchMock.mock.calls.find(([u]) => isPlainJournalEntriesListUrl(u));
    expect(firstListCall).toBeTruthy();
    expect(String(firstListCall![0])).not.toContain("needs_review");

    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Requires review"));

    await waitFor(() => {
      const listCalls = fetchMock.mock.calls.filter(([u]) => isPlainJournalEntriesListUrl(u));
      const lastUrl = String(listCalls[listCalls.length - 1]![0]);
      expect(lastUrl).toContain("needs_review=true");
    });
  });

  it("shows journal API error text from list failure", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: "service unavailable" }), { status: 503 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("service unavailable");
  });

  it("opens attachments from list and shows empty state", async () => {
    const listPayload = [
      {
        id: 7,
        entry_date: "2026-04-10",
        summary: "Rent accrual",
        description: "Test",
        requires_review: false,
        cheque_id: null,
        created_at: "2026-04-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
        debit_side_label: "Cash",
        credit_side_label: "Income",
        party_labels: "Acme Yard Maintenance",
        amount: "25.00",
      },
    ];

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries/7/attachments")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries")) {
        return new Response(JSON.stringify(listPayload), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    expect(await screen.findByText("Rent accrual")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Attachments for Rent accrual/ }));

    expect(await screen.findByRole("heading", { name: "Attachments" })).toBeInTheDocument();
    expect(await screen.findByText("No attachments yet.")).toBeInTheDocument();
  });

  it("opens attachments from journal entry details header", async () => {
    const listPayload = [
      {
        id: 7,
        entry_date: "2026-04-10",
        summary: "Rent accrual",
        description: "Test",
        requires_review: false,
        cheque_id: null,
        created_at: "2026-04-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
        debit_side_label: "Cash",
        credit_side_label: "Income",
        party_labels: "Acme Yard Maintenance",
        amount: "25.00",
      },
    ];
    const entryPayload = {
      id: 7,
      entry_date: "2026-04-10",
      summary: "Rent accrual",
      description: "Test",
      requires_review: false,
      cheque_id: null,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
      review_messages: [],
      lines: [
        {
          id: 10,
          account_id: 1,
          party_id: 1,
          amount: "25.00",
          account_name: "Cash",
          party_name: "Acme Yard Maintenance",
        },
        {
          id: 11,
          account_id: 2,
          party_id: 1,
          amount: "-25.00",
          account_name: "Income",
          party_name: "Acme Yard Maintenance",
        },
      ],
    };

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries/7/attachments")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (/\/journal-entries\/7\/?$/.test(url)) {
        return new Response(JSON.stringify(entryPayload), { status: 200 });
      }
      if (url.includes("/journal-entries")) {
        return new Response(JSON.stringify(listPayload), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: /Edit journal entry: Rent accrual/ }),
    );
    await user.click(await screen.findByRole("button", { name: "Attachments" }));

    expect(await screen.findByRole("heading", { name: "Attachments" })).toBeInTheDocument();
    expect(await screen.findByText("No attachments yet.")).toBeInTheDocument();
  });

  it("unlinks an attachment after confirmation", async () => {
    const listPayload = [
      {
        id: 7,
        entry_date: "2026-04-10",
        summary: "Rent accrual",
        description: "Test",
        requires_review: false,
        cheque_id: null,
        created_at: "2026-04-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
        debit_side_label: "Cash",
        credit_side_label: "Income",
        party_labels: "Acme Yard Maintenance",
        amount: "25.00",
      },
    ];
    const att = {
      id: 44,
      summary: "Receipt",
      external_reference: null,
      mime_type: "application/pdf",
      original_filename: "receipt.pdf",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    };
    let attachmentList: typeof att[] = [att];

    vi.spyOn(window, "confirm").mockReturnValue(true);

    const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries/7/attachments/44") && method === "DELETE") {
        attachmentList = [];
        return new Response(null, { status: 204 });
      }
      if (url.includes("/journal-entries/7/attachments")) {
        return new Response(JSON.stringify(attachmentList), { status: 200 });
      }
      if (url.includes("/journal-entries")) {
        return new Response(JSON.stringify(listPayload), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Attachments for Rent accrual/ }));
    expect(await screen.findByText("Receipt")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => {
      expect(screen.getByText("No attachments yet.")).toBeInTheDocument();
    });

    const deleteCalls = fetchMock.mock.calls.filter(
      ([u, i]) => String(u).includes("/attachments/44") && (i?.method ?? "GET") === "DELETE",
    );
    expect(deleteCalls.length).toBe(1);
  });

  it("forwards new filter dimensions as repeated query params", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/import-batches")) {
        return new Response(
          JSON.stringify([
            {
              id: 1,
              basename: "Stmt.csv",
              loaded_at: "2026-01-01T00:00:00Z",
              is_active: true,
              is_latest_loaded_import: true,
            },
          ]),
          { status: 200 },
        );
      }
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Filter by accounts" }));
    await user.click(screen.getByRole("checkbox", { name: "Cash" }));
    await user.click(screen.getByRole("checkbox", { name: "Income" }));
    await user.selectOptions(screen.getByLabelText("Filter by cheque association"), ["with_cheque"]);
    await user.type(screen.getByLabelText("Filter amount low"), "10");
    await user.type(screen.getByLabelText("Filter amount high"), "99");
    await user.selectOptions(screen.getByLabelText("Filter by CSV import file basename"), "Stmt.csv");

    await waitFor(() => {
      const listCalls = fetchMock.mock.calls.filter(([u]) => {
        const s = String(u);
        return (
          s.includes("/journal-entries")
          && !s.includes("/journal-entry-filter-presets")
          && !/\/journal-entries\/\d/.test(s)
        );
      });
      const last = String(listCalls[listCalls.length - 1]![0]);
      expect(last).toContain("account_ids=1");
      expect(last).toContain("account_ids=2");
      expect(last).toContain("cheque_association=with_cheque");
      expect(last).toContain("amount_low=10");
      expect(last).toContain("amount_high=99");
      expect(last).toContain("import_basename=Stmt.csv");
    });
  });

  it("saves the current filter as a preset via the save dialog", async () => {
    const createdPreset = {
      id: 11,
      name: "Needs review",
      definition: { needs_review: true },
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    };
    let presets: typeof createdPreset[] = [];

    const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        if (method === "POST") {
          presets = [createdPreset];
          return new Response(JSON.stringify(createdPreset), { status: 201 });
        }
        return new Response(JSON.stringify(presets), { status: 200 });
      }
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    // jsdom doesn't implement HTMLDialogElement.showModal/close.
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute("open");
    };

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("Requires review"));
    await user.click(screen.getByRole("button", { name: /Save current filter as preset/ }));
    await user.type(await screen.findByLabelText("Preset name"), "Needs review");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const postCalls = fetchMock.mock.calls.filter(([u, i]) => {
        return (
          String(u).includes("/journal-entry-filter-presets") && (i?.method ?? "GET") === "POST"
        );
      });
      expect(postCalls.length).toBe(1);
      const body = JSON.parse(String(postCalls[0]![1]!.body));
      expect(body.name).toBe("Needs review");
      expect(body.definition.needs_review).toBe(true);
    });
  });

  it("confirms before overwriting an existing preset name and uses PUT", async () => {
    const existingPreset = {
      id: 22,
      name: "Cash band",
      definition: { amount_low: 0, amount_high: 100 },
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    };

    vi.spyOn(window, "confirm").mockReturnValue(true);

    const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (
        url.includes("/journal-entry-filter-presets/22")
        && method === "PUT"
      ) {
        return new Response(
          JSON.stringify({ ...existingPreset, name: "Cash band" }),
          { status: 200 },
        );
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([existingPreset]), { status: 200 });
      }
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute("open");
    };

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    const user = userEvent.setup();
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "Cash band" })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Save current filter as preset/ }));
    const nameInput = await screen.findByLabelText("Preset name");
    await user.clear(nameInput);
    await user.type(nameInput, "Cash band");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(([u, i]) => {
        return (
          String(u).includes("/journal-entry-filter-presets/22")
          && (i?.method ?? "GET") === "PUT"
        );
      });
      expect(putCalls.length).toBe(1);
    });
    expect(window.confirm).toHaveBeenCalled();
  });

  it("applying a preset fills filters and clears selection when filters edit manually", async () => {
    const preset = {
      id: 33,
      name: "Needs review only",
      definition: { needs_review: true },
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    };

    const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([preset]), { status: 200 });
      }
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
      />,
    );

    const user = userEvent.setup();
    const presetSelect = await screen.findByLabelText("Filter preset");
    await user.selectOptions(presetSelect, ["33"]);

    expect(screen.getByLabelText("Requires review")).toBeChecked();
    expect((presetSelect as HTMLSelectElement).value).toBe("33");

    await waitFor(() => {
      const listCalls = fetchMock.mock.calls.filter(([u]) => {
        const s = String(u);
        return (
          s.includes("/journal-entries")
          && !s.includes("/journal-entry-filter-presets")
          && !/\/journal-entries\/\d/.test(s)
        );
      });
      const last = String(listCalls[listCalls.length - 1]![0]);
      expect(last).toContain("needs_review=true");
    });

    await user.click(screen.getByLabelText("Requires review"));
    expect((presetSelect as HTMLSelectElement).value).toBe("");
  });

  it("applies initialImportBasename and forwards import_basename on journal list", async () => {
    const onConsumed = vi.fn();
    const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/import-batches")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/accrual-plans")) {
        return new Response(JSON.stringify({ plans: [] }), { status: 200 });
      }
      if (url.includes("/journal-entry-filter-presets")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/cheques")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.includes("/journal-entries") && !/\/journal-entries\/\d/.test(url)) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("not mocked", { status: 500 });
    });

    render(
      <JournalEntriesPanel
        accounts={accounts}
        parties={parties}
        accountsLoading={false}
        accountsError={null}
        initialImportBasename="rent.csv"
        onInitialImportBasenameApplied={onConsumed}
      />,
    );

    await waitFor(() => expect(onConsumed).toHaveBeenCalled());
    await waitFor(() => {
      const listCalls = fetchMock.mock.calls.filter(([u]) => {
        const s = String(u);
        return s.includes("/journal-entries") && s.includes("import_basename=rent.csv");
      });
      expect(listCalls.length).toBeGreaterThan(0);
    });
  });
});
