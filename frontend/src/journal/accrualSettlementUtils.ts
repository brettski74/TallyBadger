import type { Account } from "../api/accounts";
import type { JournalEntryWrite } from "../api/journalEntries";
import type { LedgerSettings } from "../api/settlements";
import type { LineDraft } from "../components/JournalEntryForm";

function materialLines(lines: LineDraft[]): LineDraft[] {
  return lines.filter((line) => line.account_id !== "" && line.amount.trim() !== "");
}

function sumLineAmounts(lines: LineDraft[]): { sum: number; complete: boolean } {
  const material = materialLines(lines);
  let sum = 0;
  let complete = material.length > 0;
  for (const line of material) {
    const amount = parseAmount(line.amount);
    if (amount == null) {
      complete = false;
      continue;
    }
    sum += amount;
  }
  return { sum, complete };
}

const BALANCE_EPS = 1e-9;
export const ACCRUAL_BRIDGE_LINE_KEY = "accrual-bridge";

export type AccrualLineRole =
  | "pl"
  | "prepaid_unearned"
  | "bridge"
  | "settlement_cash"
  | "other";

export type AccrualSettlementDirection = "receipt" | "payment";

export interface AccrualSettlementContext {
  accrualPlanId: number;
  sourceObligationId: number;
  sourceLineId: number | null;
  planTargetAccountId: number;
  partyId: number;
  openAmount: number;
  direction: AccrualSettlementDirection;
  bridgeAccountId: number;
  defaultCashAccountId: number | null;
  prepaidUnearnedAccountIds: Set<number>;
}

function parseAmount(value: string): number | null {
  const t = value.trim();
  if (t === "" || t === "-" || t === "." || t === "-.") {
    return null;
  }
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function parseOpenAmount(value: string | null | undefined): number {
  if (value == null || value.trim() === "") {
    return 0;
  }
  const n = parseAmount(value);
  return n == null ? 0 : Math.max(0, n);
}

export function journalLineKey(lineId: number): string {
  return `jl-${lineId}`;
}

export function inferSettlementDirection(
  lines: LineDraft[],
  planTargetAccountId: number,
  accountsById: Map<number, Account>,
): AccrualSettlementDirection {
  const plLine = lines.find((line) => line.account_id === planTargetAccountId);
  if (plLine && typeof plLine.account_id === "number") {
    const account = accountsById.get(plLine.account_id);
    if (account?.type === "expense") {
      return "payment";
    }
  }
  return "receipt";
}

export function bridgeAccountIdForDirection(
  direction: AccrualSettlementDirection,
  settings: LedgerSettings,
): number | null {
  if (direction === "payment") {
    return settings.accounts_payable_account_id;
  }
  return settings.accounts_receivable_account_id;
}

export function buildAccrualSettlementContext(input: {
  accrualPlanId: number;
  sourceObligationId: number | null | undefined;
  sourceLineId: number | null | undefined;
  openAmount: string | null | undefined;
  planTargetAccountId: number | null | undefined;
  lines: LineDraft[];
  accountsById: Map<number, Account>;
  ledgerSettings: LedgerSettings;
}): AccrualSettlementContext | null {
  if (
    input.sourceObligationId == null ||
    input.planTargetAccountId == null ||
    input.planTargetAccountId <= 0
  ) {
    return null;
  }
  const direction = inferSettlementDirection(
    input.lines,
    input.planTargetAccountId,
    input.accountsById,
  );
  const bridgeAccountId = bridgeAccountIdForDirection(direction, input.ledgerSettings);
  if (bridgeAccountId == null) {
    return null;
  }
  const partyLine = input.lines.find(
    (line) => typeof line.party_id === "number" && line.party_id > 0,
  );
  const partyId = typeof partyLine?.party_id === "number" ? partyLine.party_id : 0;
  if (partyId <= 0) {
    return null;
  }
  const prepaidUnearnedAccountIds = new Set<number>();
  if (input.ledgerSettings.unearned_revenue_account_id != null) {
    prepaidUnearnedAccountIds.add(input.ledgerSettings.unearned_revenue_account_id);
  }
  if (input.ledgerSettings.prepaid_expenses_account_id != null) {
    prepaidUnearnedAccountIds.add(input.ledgerSettings.prepaid_expenses_account_id);
  }
  return {
    accrualPlanId: input.accrualPlanId,
    sourceObligationId: input.sourceObligationId,
    sourceLineId: input.sourceLineId ?? null,
    planTargetAccountId: input.planTargetAccountId,
    partyId,
    openAmount: parseOpenAmount(input.openAmount),
    direction,
    bridgeAccountId,
    defaultCashAccountId: input.ledgerSettings.default_cash_account_id,
    prepaidUnearnedAccountIds,
  };
}

export function classifyAccrualLineRole(
  line: LineDraft,
  ctx: AccrualSettlementContext,
): AccrualLineRole {
  if (
    line.obligation_id !== "" &&
    line.obligation_id != null &&
    line.obligation_id === ctx.sourceObligationId
  ) {
    return "settlement_cash";
  }
  if (line.account_id === ctx.planTargetAccountId) {
    return "pl";
  }
  if (
    typeof line.account_id === "number" &&
    ctx.prepaidUnearnedAccountIds.has(line.account_id)
  ) {
    return "prepaid_unearned";
  }
  if (line.key === ACCRUAL_BRIDGE_LINE_KEY) {
    return "bridge";
  }
  if (
    typeof line.account_id === "number" &&
    line.account_id === ctx.bridgeAccountId &&
    (line.obligation_id === "" || line.obligation_id == null)
  ) {
    return "bridge";
  }
  if (
    ctx.sourceLineId != null &&
    line.key === journalLineKey(ctx.sourceLineId) &&
    (line.obligation_id === "" || line.obligation_id == null)
  ) {
    return "bridge";
  }
  return "other";
}

export function canAddSettlementCashLine(openAmount: number): boolean {
  return openAmount > BALANCE_EPS;
}

export function settlementCashSign(direction: AccrualSettlementDirection): 1 | -1 {
  return direction === "receipt" ? 1 : -1;
}

export function createSettlementCashLine(ctx: AccrualSettlementContext): LineDraft {
  return {
    key: `cash-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    account_id: ctx.defaultCashAccountId ?? "",
    party_id: ctx.partyId,
    amount: "0.00",
    obligation_id: ctx.sourceObligationId,
  };
}

function isBridgeLine(line: LineDraft, ctx: AccrualSettlementContext): boolean {
  return classifyAccrualLineRole(line, ctx) === "bridge";
}

function isSettlementCashLine(line: LineDraft, ctx: AccrualSettlementContext): boolean {
  return classifyAccrualLineRole(line, ctx) === "settlement_cash";
}

export function sumSettlementCashAmounts(lines: LineDraft[], ctx: AccrualSettlementContext): number {
  let total = 0;
  for (const line of lines) {
    if (!isSettlementCashLine(line, ctx)) {
      continue;
    }
    const amount = parseAmount(line.amount);
    if (amount == null || Math.abs(amount) < BALANCE_EPS) {
      continue;
    }
    total += Math.abs(amount);
  }
  return total;
}

export function rebalanceAccrualBridge(
  lines: LineDraft[],
  ctx: AccrualSettlementContext,
): LineDraft[] {
  let bridgeIndex = -1;
  let sumWithoutBridge = 0;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!;
    if (isBridgeLine(line, ctx)) {
      bridgeIndex = i;
      continue;
    }
    const amount = parseAmount(line.amount);
    if (amount != null) {
      sumWithoutBridge += amount;
    }
  }
  const bridgeAmount = -sumWithoutBridge;
  if (bridgeIndex === -1) {
    if (Math.abs(bridgeAmount) < BALANCE_EPS) {
      return lines;
    }
    const bridgeLine: LineDraft = {
      key: ACCRUAL_BRIDGE_LINE_KEY,
      account_id: ctx.bridgeAccountId,
      party_id: ctx.partyId,
      amount: formatAmount(bridgeAmount),
      obligation_id: "",
    };
    const plIndex = lines.findIndex(
      (line) => classifyAccrualLineRole(line, ctx) === "pl",
    );
    const insertAt = plIndex >= 0 ? plIndex + 1 : lines.length;
    const next = [...lines];
    next.splice(insertAt, 0, bridgeLine);
    return next;
  }
  return lines.map((line, index) =>
    index === bridgeIndex ? { ...line, amount: formatAmount(bridgeAmount) } : line,
  );
}

function formatAmount(value: number): string {
  return value.toFixed(2);
}

export function mergeSettlementCashLines(
  lines: LineDraft[],
  ctx: AccrualSettlementContext,
): LineDraft[] {
  const mergedByKey = new Map<string, LineDraft>();
  const order: string[] = [];
  const passthrough: LineDraft[] = [];

  for (const line of lines) {
    if (!isSettlementCashLine(line, ctx)) {
      passthrough.push(line);
      continue;
    }
    const accountId = line.account_id;
    const partyId = line.party_id === "" ? null : line.party_id;
    if (accountId === "" || partyId == null) {
      passthrough.push(line);
      continue;
    }
    const mergeKey = `${accountId}:${partyId}`;
    const existing = mergedByKey.get(mergeKey);
    if (existing == null) {
      mergedByKey.set(mergeKey, { ...line });
      order.push(mergeKey);
      continue;
    }
    const a = parseAmount(existing.amount) ?? 0;
    const b = parseAmount(line.amount) ?? 0;
    mergedByKey.set(mergeKey, { ...existing, amount: formatAmount(a + b) });
  }

  const mergedCash = order.map((key) => mergedByKey.get(key)!);
  const bridgeAndFixed = passthrough.filter((line) => !isSettlementCashLine(line, ctx));
  const trailingCash = passthrough.filter((line) => isSettlementCashLine(line, ctx));
  return [...bridgeAndFixed, ...mergedCash, ...trailingCash];
}

function normalizeLineForCompare(line: LineDraft, ctx: AccrualSettlementContext) {
  return {
    role: classifyAccrualLineRole(line, ctx),
    account_id: line.account_id,
    party_id: line.party_id === "" ? null : line.party_id,
    amount: line.amount.trim(),
    obligation_id:
      line.obligation_id === "" || line.obligation_id == null ? null : line.obligation_id,
  };
}

export function accrualSettlementDirty(
  initialLines: LineDraft[],
  currentLines: LineDraft[],
  initialChequeId: number | null,
  currentChequeId: number | null,
  ctx: AccrualSettlementContext,
): boolean {
  if (initialChequeId !== currentChequeId) {
    return true;
  }
  const initial = JSON.stringify(initialLines.map((line) => normalizeLineForCompare(line, ctx)));
  const current = JSON.stringify(currentLines.map((line) => normalizeLineForCompare(line, ctx)));
  return initial !== current;
}

export function canEnableChequeLink(lines: LineDraft[], ctx: AccrualSettlementContext): boolean {
  const nonZeroCash = lines.filter((line) => {
    if (!isSettlementCashLine(line, ctx)) {
      return false;
    }
    const amount = parseAmount(line.amount);
    return amount != null && Math.abs(amount) >= BALANCE_EPS && line.account_id !== "";
  });
  return nonZeroCash.length === 1;
}

export function buildAccrualSettlementPayload(input: {
  entryDate: string;
  summary: string;
  description: string;
  lines: LineDraft[];
  requiresReview: boolean;
  reviewMessages: string[];
  chequeId: number | null;
  ctx: AccrualSettlementContext;
}): JournalEntryWrite {
  const balanced = rebalanceAccrualBridge(input.lines, input.ctx);
  const merged = mergeSettlementCashLines(balanced, input.ctx);
  const material = materialLines(merged).filter((line) => {
    const amount = parseAmount(line.amount);
    return amount != null && Math.abs(amount) >= BALANCE_EPS;
  });

  return {
    entry_date: input.entryDate,
    summary: input.summary.trim(),
    description: input.description.trim() === "" ? null : input.description.trim(),
    lines: material.map((line) => ({
      account_id: line.account_id as number,
      party_id: line.party_id === "" ? null : line.party_id,
      amount: line.amount.trim(),
      ...(line.obligation_id !== "" && line.obligation_id != null
        ? { obligation_id: line.obligation_id }
        : {}),
    })),
    requires_review: input.requiresReview,
    review_messages: input.reviewMessages,
    cheque_id: input.chequeId,
  };
}

export function accrualSettlementValid(
  lines: LineDraft[],
  ctx: AccrualSettlementContext,
): { ok: true } | { ok: false; message: string } {
  const balancedLines = rebalanceAccrualBridge(lines, ctx);
  const { sum, complete } = sumLineAmounts(balancedLines);
  if (!complete) {
    return { ok: false, message: "Enter a valid non-zero amount on every line that has an account." };
  }
  if (Math.abs(sum) >= BALANCE_EPS) {
    return { ok: false, message: "Debits and credits must balance (line amounts must sum to zero)." };
  }
  for (const line of materialLines(balancedLines)) {
    if (isSettlementCashLine(line, ctx) && line.account_id === "") {
      return { ok: false, message: "Each settlement cash line must have an account." };
    }
  }
  const cashTotal = sumSettlementCashAmounts(balancedLines, ctx);
  if (cashTotal - ctx.openAmount > BALANCE_EPS) {
    return {
      ok: false,
      message: `Settlement cash total (${cashTotal.toFixed(2)}) exceeds open amount (${ctx.openAmount.toFixed(2)}).`,
    };
  }
  return { ok: true };
}

export type AccrualBannerKind = "editable" | "fully_settled" | "unsettle";

export function accrualBannerKind(
  openAmount: number,
  lines: LineDraft[],
  ctx: AccrualSettlementContext,
): AccrualBannerKind {
  const hasCash = lines.some((line) => isSettlementCashLine(line, ctx));
  if (openAmount > BALANCE_EPS) {
    return "editable";
  }
  if (hasCash) {
    return "unsettle";
  }
  return "fully_settled";
}
