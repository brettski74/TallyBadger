export class ApiHttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiHttpError";
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

const VALIDATION_FIELD_LABELS: Record<string, string> = {
  party_id: "Party",
  target_account_id: "Target account",
  bridge_account_id: "Bridge account",
  name: "Plan name",
  amount: "Amount",
  start_date: "Start date",
  end_date: "End date",
  summary_template: "Summary template",
  cash_account_id: "Cash account",
};

function fieldLabelFromLoc(loc: unknown): string | null {
  if (!Array.isArray(loc) || loc.length === 0) {
    return null;
  }
  const last = loc[loc.length - 1];
  if (typeof last !== "string") {
    return null;
  }
  return VALIDATION_FIELD_LABELS[last] ?? null;
}

function formatValidationItem(item: Record<string, unknown>): string | null {
  if (typeof item.msg !== "string") {
    return null;
  }
  const fieldKey =
    Array.isArray(item.loc) && item.loc.length > 0
      ? String(item.loc[item.loc.length - 1])
      : null;
  const label = fieldLabelFromLoc(item.loc);
  if (label && item.msg === "Input should be greater than 0") {
    return `Select a ${label.toLowerCase()}.`;
  }
  if (label) {
    return `${label}: ${item.msg}`;
  }
  if (fieldKey && item.msg === "Input should be greater than 0") {
    return `${fieldKey} must be greater than 0.`;
  }
  return item.msg;
}

/** Best-effort message from FastAPI JSON error bodies (string detail or validation list). */
export function messageFromErrorBody(data: unknown): string | null {
  if (!isRecord(data)) {
    return null;
  }
  const detail = data.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => (isRecord(item) ? formatValidationItem(item) : null))
      .filter(Boolean) as string[];
    if (parts.length > 0) {
      return parts.join("; ");
    }
  }
  return null;
}

export async function readApiErrorMessage(response: Response): Promise<string> {
  try {
    const data: unknown = await response.json();
    return messageFromErrorBody(data) ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}
