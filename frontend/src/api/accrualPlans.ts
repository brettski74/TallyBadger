import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type AccrualDirection = "revenue" | "expense";
export type AccrualFrequency = "weekly" | "monthly_day" | "yearly";
export type AccrualPlanSettlementStatus =
  | "any"
  | "unsettled"
  | "open"
  | "partially_settled"
  | "settled";

export interface AccrualPlan {
  id: number;
  name: string;
  direction: AccrualDirection;
  party_id: number;
  target_account_id: number;
  bridge_account_id: number;
  frequency: AccrualFrequency;
  start_date: string;
  end_date: string;
  amount: string;
  summary_template: string;
  description_template: string | null;
  day_of_week: number | null;
  day_of_month: number | null;
  month_of_year: number | null;
  business_day_adjust: boolean;
  created_at: string;
  updated_at: string;
}

export interface AccrualPlanWrite {
  name: string;
  direction: AccrualDirection;
  party_id: number;
  target_account_id: number;
  bridge_account_id: number;
  frequency: AccrualFrequency;
  start_date: string;
  end_date: string;
  amount: string;
  summary_template: string;
  description_template: string | null;
  day_of_week?: number;
  day_of_month?: number;
  month_of_year?: number;
  business_day_adjust: boolean;
}

export interface AccrualPreviewItem {
  entry_date: string;
  summary: string;
  description: string | null;
  lines: Array<{ account_id: number; party_id: number | null; amount: string }>;
}

export interface AccrualPlanListFilterOptions {
  party_ids: number[];
  target_account_ids: number[];
  bridge_account_ids: number[];
}

export interface AccrualPlanListResponse {
  plans: AccrualPlan[];
  filter_options?: AccrualPlanListFilterOptions;
}

export interface AccrualPlanListParams {
  party_ids?: number[];
  target_account_ids?: number[];
  bridge_account_ids?: number[];
  from_date?: string;
  to_date?: string;
  name?: string;
  settlement_status?: AccrualPlanSettlementStatus;
  include_filter_options?: boolean;
}

function appendIdList(search: URLSearchParams, key: string, ids: number[] | undefined): void {
  if (!ids?.length) {
    return;
  }
  for (const id of ids) {
    search.append(key, String(id));
  }
}

export async function listAccrualPlans(
  params: AccrualPlanListParams = {},
): Promise<AccrualPlanListResponse> {
  const search = new URLSearchParams();
  appendIdList(search, "party_ids", params.party_ids);
  appendIdList(search, "target_account_ids", params.target_account_ids);
  appendIdList(search, "bridge_account_ids", params.bridge_account_ids);
  if (params.from_date) {
    search.set("from_date", params.from_date);
  }
  if (params.to_date) {
    search.set("to_date", params.to_date);
  }
  if (params.name?.trim()) {
    search.set("name", params.name.trim());
  }
  if (params.settlement_status) {
    search.set("settlement_status", params.settlement_status);
  }
  if (params.include_filter_options) {
    search.set("include_filter_options", "true");
  }
  const query = search.toString();
  const url = query ? `${getApiBase()}/accrual-plans?${query}` : `${getApiBase()}/accrual-plans`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json() as Promise<AccrualPlanListResponse>;
}

export async function previewAccrualPlan(payload: AccrualPlanWrite): Promise<AccrualPreviewItem[]> {
  const response = await fetch(`${getApiBase()}/accrual-plans/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}

export async function createAccrualPlan(payload: AccrualPlanWrite): Promise<AccrualPlan> {
  const response = await fetch(`${getApiBase()}/accrual-plans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  return response.json();
}
