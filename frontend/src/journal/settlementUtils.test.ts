import { describe, expect, it } from "vitest";

import type { Account } from "../api/accounts";
import type { LedgerSettings, Obligation } from "../api/settlements";
import {
  applyObligationSelection,
  bridgeAccountIdForObligation,
  bridgeSignForObligationType,
  clearObligationSelection,
  filterObligationsForLine,
  formatObligationOptionLabel,
  formatSignedAmount,
  isEarlyPaymentObligation,
  isEarlyReceiptObligation,
  paymentBridgeAccountId,
  receiptBridgeAccountId,
} from "./settlementUtils";

const settings: LedgerSettings = {
  accounts_receivable_account_id: 10,
  accounts_payable_account_id: 11,
  unearned_revenue_account_id: 12,
  prepaid_expenses_account_id: 13,
  unallocated_debits_account_id: null,
  unallocated_credits_account_id: null,
  default_cheque_credit_account_id: null,
  default_cheque_debit_account_id: null,
  max_attachment_upload_bytes: 5_242_880,
  max_cheque_series_count: 12,
  scanner_device_uri: null,
  max_scanned_pages: 1,
  scan_dpi: 300,
  scan_color_mode: "greyscale",
  pdf_page_size: "us-letter",
  updated_at: "2026-01-01T00:00:00Z",
};

const revenueAccount: Account = {
  id: 20,
  name: "Rent",
  type: "revenue",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const planTargetAccountByPlanId = new Map<number, number>([[7, 20], [8, 21]]);

const receivableObligation: Obligation = {
  id: 55,
  party_id: 1,
  accrual_plan_id: 7,
  source_entry_id: 100,
  source_entry_date: "2026-03-01",
  source_entry_summary: "March rent",
  obligation_type: "receivable",
  status: "open",
  original_amount: "500.00",
  open_amount: "500.00",
  due_date: null,
};

const payableObligation: Obligation = {
  id: 66,
  party_id: 1,
  accrual_plan_id: 8,
  source_entry_id: 101,
  source_entry_date: "2026-03-01",
  source_entry_summary: "Repair bill",
  obligation_type: "payable",
  status: "open",
  original_amount: "200.00",
  open_amount: "200.00",
  due_date: null,
};

describe("receiptBridgeAccountId", () => {
  it("uses A/R for due receipts and unearned for early receipts", () => {
    expect(receiptBridgeAccountId("2026-03-15", "2026-03-01", settings)).toBe(10);
    expect(receiptBridgeAccountId("2026-02-01", "2026-03-01", settings)).toBe(12);
    expect(isEarlyReceiptObligation("2026-02-01", "2026-03-01")).toBe(true);
  });
});

describe("paymentBridgeAccountId", () => {
  it("uses A/P for due payments and prepaid for early payments", () => {
    expect(paymentBridgeAccountId("2026-03-15", "2026-03-01", settings)).toBe(11);
    expect(paymentBridgeAccountId("2026-02-01", "2026-03-01", settings)).toBe(13);
    expect(isEarlyPaymentObligation("2026-02-01", "2026-03-01")).toBe(true);
  });
});

describe("filterObligationsForLine", () => {
  const accountsById = new Map<number, Account>([[20, revenueAccount]]);
  const planTargetAccountByPlanId = new Map<number, number>([[7, 20]]);

  it("filters by party and P&L account when both are set", () => {
    const result = filterObligationsForLine(
      [receivableObligation],
      { party_id: 1, account_id: 20 },
      accountsById,
      planTargetAccountByPlanId,
    );
    expect(result.mode).toBe("strict");
    expect(result.obligations).toHaveLength(1);
  });

  it("falls back to party-only when account is not P&L", () => {
    const result = filterObligationsForLine(
      [receivableObligation],
      { party_id: 1, account_id: 10 },
      accountsById,
      planTargetAccountByPlanId,
    );
    expect(result.mode).toBe("party-only");
    expect(result.obligations).toHaveLength(1);
  });
});

describe("bridgeSignForObligationType", () => {
  it("credits receivable bridges and debits payable bridges", () => {
    expect(bridgeSignForObligationType("receivable")).toBe(-1);
    expect(bridgeSignForObligationType("payable")).toBe(1);
    expect(bridgeSignForObligationType("unearned")).toBeNull();
  });
});

describe("applyObligationSelection", () => {
  it("fills receivable bridge with negative open amount when empty", () => {
    const result = applyObligationSelection({
      line: { account_id: "", party_id: 1, amount: "" },
      obligation: receivableObligation,
      entryDate: "2026-03-15",
      settings,
      accountsById: new Map(),
      planTargetAccountByPlanId,
    });
    expect(result.amount).toBe("-500.00");
    expect(result.account_id).toBe(10);
    expect(result.party_id).toBe(1);
    expect(result.remainderLine).toBeNull();
  });

  it("fills payable bridge with positive open amount when empty", () => {
    const result = applyObligationSelection({
      line: { account_id: "", party_id: 1, amount: "" },
      obligation: payableObligation,
      entryDate: "2026-03-15",
      settings,
      accountsById: new Map(),
      planTargetAccountByPlanId,
    });
    expect(result.amount).toBe("200.00");
    expect(result.account_id).toBe(11);
  });

  it("replaces P&L account with bridge and caps excess with remainder line", () => {
    const result = applyObligationSelection({
      line: { account_id: 20, party_id: 1, amount: "600.00" },
      obligation: receivableObligation,
      entryDate: "2026-03-15",
      settings,
      accountsById: new Map([[20, revenueAccount]]),
      planTargetAccountByPlanId,
    });
    expect(result.amount).toBe("-500.00");
    expect(result.account_id).toBe(10);
    expect(result.remainderLine).toEqual({
      account_id: 20,
      party_id: 1,
      amount: "100.00",
    });
  });

  it("replaces an existing bridge account when switching obligations", () => {
    const futurePayable: Obligation = {
      ...payableObligation,
      source_entry_date: "2026-06-01",
    };
    const result = applyObligationSelection({
      line: { account_id: 11, party_id: 1, amount: "200.00" },
      obligation: futurePayable,
      entryDate: "2026-03-15",
      settings,
      accountsById: new Map(),
      planTargetAccountByPlanId,
    });
    expect(result.account_id).toBe(13);
  });

  it("uses plan P&L for remainder when prior account was a bridge", () => {
    const expenseAccount: Account = {
      id: 21,
      name: "Repairs",
      type: "expense",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const result = applyObligationSelection({
      line: { account_id: 11, party_id: 1, amount: "300.00" },
      obligation: payableObligation,
      entryDate: "2026-03-15",
      settings,
      accountsById: new Map([[21, expenseAccount]]),
      planTargetAccountByPlanId,
    });
    expect(result.amount).toBe("200.00");
    expect(result.account_id).toBe(11);
    expect(result.remainderLine).toEqual({
      account_id: 21,
      party_id: 1,
      amount: "100.00",
    });
  });

  it("resolves bridge from obligation type", () => {
    expect(bridgeAccountIdForObligation(receivableObligation, "2026-03-15", settings)).toBe(10);
  });
});

describe("clearObligationSelection", () => {
  it("restores plan P&L when clearing a bridge account line", () => {
    const result = clearObligationSelection({
      line: { account_id: 11 },
      removedObligation: payableObligation,
      obligationTargetAccountId: null,
      settings,
      planTargetAccountByPlanId,
    });
    expect(result.account_id).toBe(21);
  });

  it("uses saved target account when the obligation is no longer open", () => {
    const result = clearObligationSelection({
      line: { account_id: 11 },
      removedObligation: null,
      obligationTargetAccountId: 21,
      settings,
      planTargetAccountByPlanId,
    });
    expect(result.account_id).toBe(21);
  });
});

describe("formatObligationOptionLabel", () => {
  it("formats open and saved obligation options", () => {
    expect(
      formatObligationOptionLabel(48, "Snow removal 2026-02", {
        kind: "open",
        openAmount: "1500.00",
      }),
    ).toBe("#48 — Snow removal 2026-02 (1500.00 open)");
    expect(formatObligationOptionLabel(48, "Snow removal 2026-02", { kind: "saved" })).toBe(
      "#48 — Snow removal 2026-02 (saved)",
    );
    expect(formatObligationOptionLabel(48, null, { kind: "saved" })).toBe("#48 — obligation (saved)");
  });
});

describe("formatSignedAmount", () => {
  it("applies sign to magnitude", () => {
    expect(formatSignedAmount("42.5", true)).toBe("42.50");
    expect(formatSignedAmount("42.5", false)).toBe("-42.50");
  });
});
