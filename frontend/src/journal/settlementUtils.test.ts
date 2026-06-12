import { describe, expect, it } from "vitest";

import type { Account } from "../api/accounts";
import type { LedgerSettings, Obligation } from "../api/settlements";
import {
  applyObligationSelection,
  bridgeAccountIdForObligation,
  filterObligationsForLine,
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

describe("applyObligationSelection", () => {
  it("fills amount and bridge account when empty", () => {
    const result = applyObligationSelection({
      line: { account_id: "", party_id: 1, amount: "" },
      obligation: receivableObligation,
      entryDate: "2026-03-15",
      settings,
      accountsById: new Map(),
    });
    expect(result.amount).toBe("500.00");
    expect(result.account_id).toBe(10);
    expect(result.party_id).toBe(1);
    expect(result.remainderLine).toBeNull();
  });

  it("replaces P&L account with bridge and caps excess with remainder line", () => {
    const result = applyObligationSelection({
      line: { account_id: 20, party_id: 1, amount: "600.00" },
      obligation: receivableObligation,
      entryDate: "2026-03-15",
      settings,
      accountsById: new Map([[20, revenueAccount]]),
    });
    expect(result.amount).toBe("500.00");
    expect(result.account_id).toBe(10);
    expect(result.remainderLine).toEqual({
      account_id: 20,
      party_id: 1,
      amount: "100.00",
    });
  });

  it("resolves bridge from obligation type", () => {
    expect(bridgeAccountIdForObligation(receivableObligation, "2026-03-15", settings)).toBe(10);
  });
});

describe("formatSignedAmount", () => {
  it("applies sign to magnitude", () => {
    expect(formatSignedAmount("42.5", true)).toBe("42.50");
    expect(formatSignedAmount("42.5", false)).toBe("-42.50");
  });
});
