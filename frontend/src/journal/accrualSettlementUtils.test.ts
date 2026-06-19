import { describe, expect, it } from "vitest";

import type { Account } from "../api/accounts";
import type { LedgerSettings } from "../api/settlements";
import type { LineDraft } from "../components/JournalEntryForm";
import {
  ACCRUAL_BRIDGE_LINE_KEY,
  accrualSettlementDirty,
  buildAccrualSettlementPayload,
  buildAccrualSettlementContext,
  canAddSettlementCashLine,
  canEnableChequeLink,
  classifyAccrualLineRole,
  createSettlementCashLine,
  mergeSettlementCashLines,
  rebalanceAccrualBridge,
  sumSettlementCashAmounts,
} from "./accrualSettlementUtils";

const ledgerSettings: LedgerSettings = {
  accounts_receivable_account_id: 10,
  accounts_payable_account_id: 11,
  unearned_revenue_account_id: 12,
  prepaid_expenses_account_id: 13,
  unallocated_debits_account_id: null,
  unallocated_credits_account_id: null,
  default_cheque_credit_account_id: null,
  default_cheque_debit_account_id: null,
  default_cash_account_id: 1,
  max_attachment_upload_bytes: 5_242_880,
  max_cheque_series_count: 12,
  scanner_device_uri: null,
  max_scanned_pages: 1,
  scan_dpi: 300,
  scan_color_mode: "greyscale",
  pdf_page_size: "us-letter",
  updated_at: "2026-04-01T00:00:00Z",
};

const accountsById = new Map<number, Account>([
  [
    1,
    {
      id: 1,
      name: "Cash",
      type: "asset",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ],
  [
    2,
    {
      id: 2,
      name: "Rent Revenue",
      type: "revenue",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ],
  [
    10,
    {
      id: 10,
      name: "Accounts Receivable",
      type: "asset",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ],
  [
    12,
    {
      id: 12,
      name: "Unearned Revenue",
      type: "liability",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
    },
  ],
]);

const baseLines: LineDraft[] = [
  { key: "pl", account_id: 2, party_id: 1, amount: "-1500.00", obligation_id: "" },
  { key: "jl-20", account_id: 10, party_id: 1, amount: "1500.00", obligation_id: "" },
];

function ctx(openAmount = "1500.00") {
  return buildAccrualSettlementContext({
    accrualPlanId: 9,
    sourceObligationId: 44,
    sourceLineId: 20,
    openAmount,
    planTargetAccountId: 2,
    lines: baseLines,
    accountsById,
    ledgerSettings,
  })!;
}

describe("accrualSettlementUtils", () => {
  it("classifies accrual line roles", () => {
    const settlementCtx = ctx();
    expect(classifyAccrualLineRole(baseLines[0]!, settlementCtx)).toBe("pl");
    expect(classifyAccrualLineRole(baseLines[1]!, settlementCtx)).toBe("bridge");
    expect(
      classifyAccrualLineRole(
        { key: "cash", account_id: 1, party_id: 1, amount: "500.00", obligation_id: 44 },
        settlementCtx,
      ),
    ).toBe("settlement_cash");
    expect(
      classifyAccrualLineRole(
        { key: "ur", account_id: 12, party_id: 1, amount: "500.00", obligation_id: "" },
        settlementCtx,
      ),
    ).toBe("prepaid_unearned");
  });

  it("gates add line on open amount", () => {
    expect(canAddSettlementCashLine(1000)).toBe(true);
    expect(canAddSettlementCashLine(0)).toBe(false);
  });

  it("creates settlement cash lines with default cash account and obligation", () => {
    const settlementCtx = ctx("1000.00");
    const line = createSettlementCashLine(settlementCtx);
    expect(line.account_id).toBe(1);
    expect(line.party_id).toBe(1);
    expect(line.obligation_id).toBe(44);
    expect(line.amount).toBe("0.00");
  });

  it("rebalances only the bridge line when cash changes", () => {
    const settlementCtx = ctx("1500.00");
    const lines: LineDraft[] = [
      ...baseLines,
      { key: "cash", account_id: 1, party_id: 1, amount: "500.00", obligation_id: 44 },
    ];
    const rebalanced = rebalanceAccrualBridge(lines, settlementCtx);
    const bridge = rebalanced.find((line) => line.key === "jl-20");
    const pl = rebalanced.find((line) => line.key === "pl");
    const cash = rebalanced.find((line) => line.key === "cash");
    expect(pl?.amount).toBe("-1500.00");
    expect(cash?.amount).toBe("500.00");
    expect(bridge?.amount).toBe("1000.00");
  });

  it("injects a bridge line when a collapsed entry becomes unbalanced", () => {
    const settlementCtx = ctx("500.00");
    const lines: LineDraft[] = [
      { key: "pl", account_id: 2, party_id: 1, amount: "-1500.00", obligation_id: "" },
      { key: "jl-30", account_id: 1, party_id: 1, amount: "1000.00", obligation_id: 44 },
    ];
    const rebalanced = rebalanceAccrualBridge(lines, settlementCtx);
    const bridge = rebalanced.find((line) => line.key === ACCRUAL_BRIDGE_LINE_KEY);
    expect(bridge?.account_id).toBe(10);
    expect(bridge?.amount).toBe("500.00");
  });

  it("merges same-account settlement cash lines on save", () => {
    const settlementCtx = ctx("1500.00");
    const lines: LineDraft[] = [
      ...baseLines,
      { key: "cash-a", account_id: 1, party_id: 1, amount: "400.00", obligation_id: 44 },
      { key: "cash-b", account_id: 1, party_id: 1, amount: "100.00", obligation_id: 44 },
    ];
    const merged = mergeSettlementCashLines(lines, settlementCtx);
    const cashLines = merged.filter((line) => line.obligation_id === 44);
    expect(cashLines).toHaveLength(1);
    expect(cashLines[0]?.amount).toBe("500.00");
  });

  it("enables cheque linking only for one non-zero settlement cash line", () => {
    const settlementCtx = ctx("1500.00");
    expect(
      canEnableChequeLink(
        [
          ...baseLines,
          { key: "cash", account_id: 1, party_id: 1, amount: "500.00", obligation_id: 44 },
        ],
        settlementCtx,
      ),
    ).toBe(true);
    expect(
      canEnableChequeLink(
        [
          ...baseLines,
          { key: "cash-a", account_id: 1, party_id: 1, amount: "300.00", obligation_id: 44 },
          { key: "cash-b", account_id: 1, party_id: 1, amount: "200.00", obligation_id: 44 },
        ],
        settlementCtx,
      ),
    ).toBe(false);
  });

  it("builds PUT payload from display lines", () => {
    const settlementCtx = ctx("1500.00");
    const payload = buildAccrualSettlementPayload({
      entryDate: "2026-07-01",
      summary: "July rent",
      description: "",
      requiresReview: false,
      reviewMessages: [],
      chequeId: null,
      ctx: settlementCtx,
      lines: [
        ...baseLines,
        { key: "cash-a", account_id: 1, party_id: 1, amount: "300.00", obligation_id: 44 },
        { key: "cash-b", account_id: 1, party_id: 1, amount: "200.00", obligation_id: 44 },
      ],
    });
    const cashLines = payload.lines.filter((line) => line.obligation_id === 44);
    expect(cashLines).toHaveLength(1);
    expect(cashLines[0]?.amount).toBe("500.00");
    expect(payload.lines.some((line) => line.obligation_id == null)).toBe(true);
  });

  it("detects settlement dirty state", () => {
    const settlementCtx = ctx("1500.00");
    const initial = [
      ...baseLines,
      { key: "cash", account_id: 1, party_id: 1, amount: "500.00", obligation_id: 44 },
    ];
    const unchanged = accrualSettlementDirty(initial, initial, null, null, settlementCtx);
    const changed = accrualSettlementDirty(
      initial,
      [
        ...baseLines,
        { key: "cash", account_id: 1, party_id: 1, amount: "600.00", obligation_id: 44 },
      ],
      null,
      null,
      settlementCtx,
    );
    expect(unchanged).toBe(false);
    expect(changed).toBe(true);
    expect(sumSettlementCashAmounts(initial, settlementCtx)).toBe(500);
  });
});
