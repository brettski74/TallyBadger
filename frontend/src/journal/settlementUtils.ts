import type { Account } from "../api/accounts";
import type { LedgerSettings, Obligation } from "../api/settlements";

export type ObligationFilterMode = "strict" | "party-only";

export interface FilteredObligations {
  obligations: Obligation[];
  mode: ObligationFilterMode;
}

function parseDecimal(value: string): number | null {
  const t = value.trim();
  if (t === "" || t === "-" || t === "." || t === "-.") {
    return null;
  }
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function isEarlyReceiptObligation(eventDate: string, sourceEntryDate: string | null): boolean {
  return sourceEntryDate != null && sourceEntryDate > eventDate;
}

export function isEarlyPaymentObligation(eventDate: string, sourceEntryDate: string | null): boolean {
  return sourceEntryDate != null && sourceEntryDate > eventDate;
}

export function receiptBridgeAccountId(
  eventDate: string,
  sourceEntryDate: string | null,
  settings: Pick<
    LedgerSettings,
    "accounts_receivable_account_id" | "unearned_revenue_account_id"
  >,
): number | null {
  if (isEarlyReceiptObligation(eventDate, sourceEntryDate)) {
    return settings.unearned_revenue_account_id;
  }
  return settings.accounts_receivable_account_id;
}

export function paymentBridgeAccountId(
  eventDate: string,
  sourceEntryDate: string | null,
  settings: Pick<LedgerSettings, "accounts_payable_account_id" | "prepaid_expenses_account_id">,
): number | null {
  if (isEarlyPaymentObligation(eventDate, sourceEntryDate)) {
    return settings.prepaid_expenses_account_id;
  }
  return settings.accounts_payable_account_id;
}

export function bridgeAccountIdForObligation(
  obligation: Obligation,
  eventDate: string,
  settings: LedgerSettings,
): number | null {
  if (obligation.obligation_type === "receivable") {
    return receiptBridgeAccountId(eventDate, obligation.source_entry_date, settings);
  }
  if (obligation.obligation_type === "payable") {
    return paymentBridgeAccountId(eventDate, obligation.source_entry_date, settings);
  }
  return null;
}

export function bridgeSignForObligationType(
  obligationType: Obligation["obligation_type"],
): 1 | -1 | null {
  if (obligationType === "receivable") {
    return 1;
  }
  if (obligationType === "payable") {
    return -1;
  }
  return null;
}

export function formatSignedAmount(magnitude: string, positive: boolean): string {
  const n = parseDecimal(magnitude);
  if (n === null) {
    return magnitude.trim();
  }
  const abs = Math.abs(n);
  const formatted = abs.toFixed(2);
  return positive ? formatted : `-${formatted}`;
}

export function isPlAccount(account: Account | undefined): boolean {
  return account?.type === "revenue" || account?.type === "expense";
}

export function filterObligationsForLine(
  allForParty: Obligation[],
  line: { party_id: number | ""; account_id: number | "" },
  accountsById: Map<number, Account>,
  planTargetAccountByPlanId: Map<number, number>,
): FilteredObligations {
  if (line.party_id === "") {
    return { obligations: [], mode: "party-only" };
  }

  const partyObligations = allForParty.filter((o) => o.party_id === line.party_id);
  if (line.account_id === "") {
    return { obligations: partyObligations, mode: "party-only" };
  }

  const account = accountsById.get(line.account_id);
  if (!account || !isPlAccount(account)) {
    return { obligations: partyObligations, mode: "party-only" };
  }

  const obligationType = account.type === "revenue" ? "receivable" : "payable";
  const filtered = partyObligations.filter(
    (o) =>
      o.obligation_type === obligationType &&
      o.accrual_plan_id != null &&
      planTargetAccountByPlanId.get(o.accrual_plan_id) === account.id,
  );
  return { obligations: filtered, mode: "strict" };
}

export interface ApplyObligationSelectionInput {
  line: {
    account_id: number | "";
    party_id: number | "";
    amount: string;
  };
  obligation: Obligation;
  entryDate: string;
  settings: LedgerSettings;
  accountsById: Map<number, Account>;
}

export interface ApplyObligationSelectionResult {
  account_id: number | "";
  party_id: number | "";
  amount: string;
  remainderLine: { account_id: number | ""; party_id: number | ""; amount: string } | null;
}

/** Automation when the user picks an obligation on a journal line (#272). */
export function applyObligationSelection(
  input: ApplyObligationSelectionInput,
): ApplyObligationSelectionResult {
  const { line, obligation, entryDate, settings, accountsById } = input;
  const priorAccountId = line.account_id;
  const sign = bridgeSignForObligationType(obligation.obligation_type);
  const bridgeId = bridgeAccountIdForObligation(obligation, entryDate, settings);

  let account_id: number | "" = line.account_id;
  if (account_id === "" && bridgeId != null) {
    account_id = bridgeId;
  } else if (
    priorAccountId !== "" &&
    isPlAccount(accountsById.get(priorAccountId)) &&
    bridgeId != null
  ) {
    account_id = bridgeId;
  }

  const openAmount = parseDecimal(obligation.open_amount) ?? 0;
  const parsedAmount = parseDecimal(line.amount);
  let amount = line.amount;
  let remainderLine: ApplyObligationSelectionResult["remainderLine"] = null;

  if (parsedAmount === null || line.amount.trim() === "") {
    if (sign != null) {
      amount = formatSignedAmount(obligation.open_amount, sign > 0);
    }
  } else if (sign != null && Math.abs(parsedAmount) > openAmount + 1e-9) {
    amount = formatSignedAmount(obligation.open_amount, sign > 0);
    const remainderMag = (Math.abs(parsedAmount) - openAmount).toFixed(2);
    const remainderPositive = parsedAmount > 0;
    remainderLine = {
      account_id: priorAccountId === "" ? "" : priorAccountId,
      party_id: obligation.party_id,
      amount: formatSignedAmount(remainderMag, remainderPositive),
    };
  }

  return {
    account_id,
    party_id: obligation.party_id,
    amount,
    remainderLine,
  };
}
