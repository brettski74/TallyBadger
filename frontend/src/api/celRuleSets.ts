import { getApiBase } from "./baseUrl";
import { ApiHttpError, messageFromErrorBody, readApiErrorMessage } from "./errors";

export interface CelRuleSetValidationErrorItem {
  rule_index: number;
  rule_label: string;
  field: "expression" | "pattern";
  message: string;
  capture_index?: number;
  matcher_label?: string;
}

export class CelRuleSetSaveValidationError extends Error {
  readonly status = 422;
  readonly errors: CelRuleSetValidationErrorItem[];

  constructor(errors: CelRuleSetValidationErrorItem[]) {
    super("Rule set validation failed");
    this.name = "CelRuleSetSaveValidationError";
    this.errors = errors;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseValidationErrorsFromBody(data: unknown): CelRuleSetValidationErrorItem[] | null {
  if (!isRecord(data)) {
    return null;
  }
  const detail = data.detail;
  if (!isRecord(detail) || !Array.isArray(detail.errors)) {
    return null;
  }
  const items: CelRuleSetValidationErrorItem[] = [];
  for (const raw of detail.errors) {
    if (!isRecord(raw)) {
      continue;
    }
    if (
      typeof raw.rule_index !== "number" ||
      typeof raw.rule_label !== "string" ||
      (raw.field !== "expression" && raw.field !== "pattern") ||
      typeof raw.message !== "string"
    ) {
      continue;
    }
    items.push({
      rule_index: raw.rule_index,
      rule_label: raw.rule_label,
      field: raw.field,
      message: raw.message,
      capture_index: typeof raw.capture_index === "number" ? raw.capture_index : undefined,
      matcher_label: typeof raw.matcher_label === "string" ? raw.matcher_label : undefined,
    });
  }
  return items.length > 0 ? items : null;
}

export interface CelRuleSetSummary {
  id: number;
  name: string;
  updated_at: string;
}

export interface CelRegexCapture {
  attribute: string;
  pattern: string;
  flags: string[];
  label: string | null;
}

export interface CelRule {
  name: string | null;
  enabled: boolean;
  sort_order: number;
  expression: string;
  captures: CelRegexCapture[];
}

export interface CelRuleSet {
  rules: CelRule[];
}

export interface CelRuleSetStored extends CelRuleSetSummary {
  rule_set: CelRuleSet;
  created_at: string;
}

export interface CreateCelRuleSetPayload {
  name: string;
  rule_set: CelRuleSet;
}

export interface PatchCelRuleSetPayload {
  name?: string;
  rule_set?: CelRuleSet;
}

async function throwIfNotOk(response: Response): Promise<void> {
  if (!response.ok) {
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    if (response.status === 422) {
      const validationErrors = parseValidationErrorsFromBody(data);
      if (validationErrors) {
        throw new CelRuleSetSaveValidationError(validationErrors);
      }
    }
    const message =
      (data != null ? messageFromErrorBody(data) : null) ?? `Request failed (${response.status})`;
    throw new ApiHttpError(response.status, message);
  }
}

function normalizeStored(raw: CelRuleSetStored): CelRuleSetStored {
  const rules = raw.rule_set.rules.map((r) => ({
    ...r,
    captures: r.captures.map((c) => ({
      ...c,
      label: c.label ?? null,
      flags: c.flags ?? [],
    })),
  }));
  return { ...raw, rule_set: { rules } };
}

export async function listCelRuleSets(): Promise<CelRuleSetSummary[]> {
  const response = await fetch(`${getApiBase()}/import-rules/cel/rule-sets`);
  await throwIfNotOk(response);
  return response.json();
}

export async function getCelRuleSet(ruleSetId: number): Promise<CelRuleSetStored> {
  const response = await fetch(`${getApiBase()}/import-rules/cel/rule-sets/${ruleSetId}`);
  await throwIfNotOk(response);
  return normalizeStored(await response.json());
}

export async function createCelRuleSet(payload: CreateCelRuleSetPayload): Promise<CelRuleSetStored> {
  const response = await fetch(`${getApiBase()}/import-rules/cel/rule-sets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await throwIfNotOk(response);
  return normalizeStored(await response.json());
}

export async function patchCelRuleSet(
  ruleSetId: number,
  payload: PatchCelRuleSetPayload,
): Promise<CelRuleSetStored> {
  const response = await fetch(`${getApiBase()}/import-rules/cel/rule-sets/${ruleSetId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await throwIfNotOk(response);
  return normalizeStored(await response.json());
}

export async function deleteCelRuleSet(ruleSetId: number): Promise<void> {
  const response = await fetch(`${getApiBase()}/import-rules/cel/rule-sets/${ruleSetId}`, {
    method: "DELETE",
  });
  if (response.status === 204) {
    return;
  }
  throw new ApiHttpError(response.status, await readApiErrorMessage(response));
}
