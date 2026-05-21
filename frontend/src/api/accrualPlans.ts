import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export type AccrualDirection = "revenue" | "expense";
export type AccrualFrequency = "weekly" | "monthly_day" | "yearly";

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

export async function listAccrualPlans(): Promise<AccrualPlan[]> {
  const response = await fetch(`${getApiBase()}/accrual-plans`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  const body = (await response.json()) as AccrualPlanListResponse;
  return body.plans;
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
