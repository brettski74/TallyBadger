import { getApiBase } from "./baseUrl";
import { ApiHttpError, readApiErrorMessage } from "./errors";

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
    throw new ApiHttpError(response.status, await readApiErrorMessage(response));
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
