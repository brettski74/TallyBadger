import { getApiBase } from "./baseUrl";
import { messageFromErrorBody, parseDetailErrorsArray, readApiErrorMessage } from "./errors";

export class LedgerSettingsValidationError extends Error {
  readonly status = 422;
  readonly errors: string[];

  constructor(errors: string[]) {
    super("Ledger settings validation failed");
    this.name = "LedgerSettingsValidationError";
    this.errors = errors;
  }
}

export interface LedgerSettings {
  accounts_receivable_account_id: number | null;
  accounts_payable_account_id: number | null;
  unearned_revenue_account_id: number | null;
  prepaid_expenses_account_id: number | null;
  unallocated_debits_account_id: number | null;
  unallocated_credits_account_id: number | null;
  /** Last credit (cheque/bank register) account saved; pre-fills the next new cheque when still eligible (#105). */
  default_cheque_credit_account_id: number | null;
  /** Last debit (counter-account) saved on a cheque; pre-fills the next new cheque when still eligible (#105). */
  default_cheque_debit_account_id: number | null;
  /** Maximum journal attachment upload size in bytes (default 5 MiB). PATCH may use a string with `k` or `M` suffix. */
  max_attachment_upload_bytes: number;
  /** Maximum cheques in one post-dated series (#141). */
  max_cheque_series_count: number;
  /** SANE/HPLIP device URI for flatbed scanning (#258). */
  scanner_device_uri: string | null;
  /** Guard for future multi-page scan sessions (#258). */
  max_scanned_pages: number;
  /** Flatbed scan resolution in dpi (#258). */
  scan_dpi: number;
  /** Flatbed scan colour mode (#258; v1 greyscale only). */
  scan_color_mode: string;
  updated_at: string;
}

export interface Obligation {
  id: number;
  party_id: number;
  source_entry_id: number | null;
  source_entry_date: string | null;
  source_entry_summary: string | null;
  obligation_type: "receivable" | "payable" | "unearned";
  status: "open" | "partially_settled" | "settled" | "reconciled";
  original_amount: string;
  open_amount: string;
}

export interface SettlementAllocation {
  obligation_id: number;
  amount: string;
}

export interface SettlementPayload {
  party_id: number;
  settlement_type: "receipt" | "payment";
  event_date: string;
  amount: string;
  cash_account_id: number;
  allocations: SettlementAllocation[];
  note: string | null;
}

export async function getLedgerSettings(): Promise<LedgerSettings> {
  const response = await fetch(`${getApiBase()}/ledger-settings`);
  if (!response.ok) throw new Error(await readApiErrorMessage(response));
  return response.json();
}

export async function updateLedgerSettings(payload: Partial<LedgerSettings>): Promise<LedgerSettings> {
  const response = await fetch(`${getApiBase()}/ledger-settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    if (response.status === 422) {
      const validationErrors = data != null ? parseDetailErrorsArray(data) : null;
      if (validationErrors) {
        throw new LedgerSettingsValidationError(validationErrors);
      }
    }
    throw new Error(
      (data != null ? messageFromErrorBody(data) : null) ?? `Request failed (${response.status})`,
    );
  }
  return response.json();
}

export async function listOpenObligations(partyId: number): Promise<Obligation[]> {
  const response = await fetch(`${getApiBase()}/obligations/${partyId}`);
  if (!response.ok) throw new Error(await readApiErrorMessage(response));
  return response.json();
}

export async function createSettlement(payload: SettlementPayload) {
  const response = await fetch(`${getApiBase()}/settlements`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readApiErrorMessage(response));
  return response.json();
}
