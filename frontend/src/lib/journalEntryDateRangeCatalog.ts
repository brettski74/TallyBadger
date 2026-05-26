/** Quick-range catalogue for journal entry date filters (#133). Not persisted — reverse-match only. */

export type JournalQuickRangeId =
  | "ytd"
  | "mtd"
  | "last-month"
  | "last-year"
  | "last-7-days"
  | "last-30-days"
  | "custom";

export interface JournalQuickRangeOption {
  id: JournalQuickRangeId;
  label: string;
  fromExpr: string;
  toExpr: string;
}

export const JOURNAL_QUICK_RANGE_OPTIONS: JournalQuickRangeOption[] = [
  { id: "ytd", label: "Year to date (YTD)", fromExpr: "now/y", toExpr: "now" },
  { id: "mtd", label: "Month to date (MTD)", fromExpr: "now/M", toExpr: "now" },
  { id: "last-month", label: "Last month", fromExpr: "now-1M/M", toExpr: "now/M-1d" },
  { id: "last-year", label: "Last year", fromExpr: "now-1y/y", toExpr: "now/y-1d" },
  { id: "last-7-days", label: "Last 7 days", fromExpr: "now-7d", toExpr: "now" },
  { id: "last-30-days", label: "Last 30 days", fromExpr: "now-30d", toExpr: "now" },
];

export const JOURNAL_QUICK_RANGE_CUSTOM: JournalQuickRangeOption = {
  id: "custom",
  label: "Custom",
  fromExpr: "",
  toExpr: "",
};

export function matchQuickRangeId(fromExpr: string, toExpr: string): JournalQuickRangeId {
  const fromClean = fromExpr.trim();
  const toClean = toExpr.trim();
  if (!fromClean || !toClean) {
    return "custom";
  }
  for (const option of JOURNAL_QUICK_RANGE_OPTIONS) {
    if (fromClean === option.fromExpr && toClean === option.toExpr) {
      return option.id;
    }
  }
  return "custom";
}
