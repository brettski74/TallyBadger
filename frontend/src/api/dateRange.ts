import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export interface DateRangeResolveResult {
  date?: string | null;
  from_date?: string | null;
  to_date?: string | null;
}

export async function resolveDateExpression(expr: string): Promise<string> {
  const base = getApiBase();
  const search = new URLSearchParams({ expr });
  const response = await fetch(`${base}/date-range/resolve?${search.toString()}`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  const body = (await response.json()) as DateRangeResolveResult;
  if (!body.date) {
    throw new Error("resolve response missing date");
  }
  return body.date;
}

export async function resolveDateRange(fromExpr: string, toExpr: string): Promise<{
  from_date: string;
  to_date: string;
}> {
  const base = getApiBase();
  const search = new URLSearchParams({ from: fromExpr, to: toExpr });
  const response = await fetch(`${base}/date-range/resolve?${search.toString()}`);
  if (!response.ok) {
    throw new Error(await readApiErrorMessage(response));
  }
  const body = (await response.json()) as DateRangeResolveResult;
  if (!body.from_date || !body.to_date) {
    throw new Error("resolve response missing from_date or to_date");
  }
  return { from_date: body.from_date, to_date: body.to_date };
}
