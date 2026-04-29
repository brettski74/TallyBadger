import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export interface CelRuleSetSummary {
  id: number;
  name: string;
  updated_at: string;
}

export async function listCelRuleSets(): Promise<CelRuleSetSummary[]> {
  const response = await fetch(`${getApiBase()}/import-rules/cel/rule-sets`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}
