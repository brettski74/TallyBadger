import { FormEvent, useCallback, useState } from "react";

import {
  type FetchIncomeExpenseParams,
  type IncomeExpensePreset,
  type IncomeExpenseReport,
  fetchIncomeExpenseReport,
  incomeExpenseExportUrl,
} from "../api/incomeExpenseReport";

function localCalendarTodayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Formats API decimal strings for on-screen P&L preview (USD, 2 dp, grouping). */
function formatReportCurrency(amountStr: string): string {
  const n = Number(amountStr);
  if (!Number.isFinite(n)) {
    return amountStr;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

type PeriodMode = "custom" | IncomeExpensePreset;

export function IncomeExpenseReportSection() {
  const [periodMode, setPeriodMode] = useState<PeriodMode>("current_year_to_date");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [excludeZeros, setExcludeZeros] = useState(false);
  const [report, setReport] = useState<IncomeExpenseReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildParams = useCallback((): FetchIncomeExpenseParams => {
    const base = { excludeZeroBalanceAccounts: excludeZeros };
    if (periodMode === "custom") {
      return { ...base, startDate: customStart, endDate: customEnd };
    }
    return { ...base, preset: periodMode, asOfDate: localCalendarTodayIso() };
  }, [customEnd, customStart, excludeZeros, periodMode]);

  async function runReport(event?: FormEvent) {
    event?.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (periodMode === "custom" && (!customStart || !customEnd)) {
        throw new Error("Choose both start and end dates for a custom range.");
      }
      const data = await fetchIncomeExpenseReport(buildParams());
      setReport(data);
    } catch (err) {
      setReport(null);
      setError(err instanceof Error ? err.message : "Failed to load report");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card journal-card-wide" aria-labelledby="income-expense-heading">
      <h2 id="income-expense-heading">Income &amp; expense report</h2>
      <p className="muted">
        Operating P&amp;L-style totals from posted revenue and expense accounts. Amounts use natural signs
        (revenue and expenses shown as positive operating figures); ledger lines remain debit-positive /
        credit-negative.
      </p>

      <form className="journal-filters" onSubmit={(e) => void runReport(e)}>
        <div>
          <label htmlFor="period-preset">Period</label>
          <select
            id="period-preset"
            value={periodMode}
            onChange={(e) => setPeriodMode(e.target.value as PeriodMode)}
          >
            <option value="current_year_to_date">Current year to date (calendar year)</option>
            <option value="prior_full_year">Prior full calendar year</option>
            <option value="prior_year_to_date">Prior year to date (same month-day)</option>
            <option value="custom">Custom range</option>
          </select>
        </div>
        {periodMode === "custom" && (
          <div className="journal-filters">
            <div>
              <label htmlFor="custom-start">Start</label>
              <input
                id="custom-start"
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="custom-end">End</label>
              <input
                id="custom-end"
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
              />
            </div>
          </div>
        )}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={excludeZeros}
            onChange={(e) => setExcludeZeros(e.target.checked)}
          />
          Exclude zero-balance accounts (totals still include full period)
        </label>
        <div className="form-actions-inline">
          <button type="submit" disabled={loading}>
            {loading ? "Loading…" : "Run report"}
          </button>
        </div>
      </form>

      {error && <p role="alert">{error}</p>}

      {report && (
        <div className="report-output income-exp-report">
          <p>
            <strong>Period:</strong> {report.period.start_date} to {report.period.end_date}
            {report.preset && (
              <span className="muted">
                {" "}
                (preset: {report.preset.replace(/_/g, " ")})
              </span>
            )}
          </p>
          <h3>Revenue accounts</h3>
          <table className="journal-entry-list income-exp-report-table">
            <thead>
              <tr>
                <th scope="col">Account</th>
                <th className="journal-list-amount" scope="col">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {report.revenue_accounts.map((row) => (
                <tr key={row.account_id}>
                  <td>
                    {row.account_name}
                    {!row.is_active && <span className="muted"> (inactive)</span>}
                  </td>
                  <td className="journal-list-amount">{formatReportCurrency(row.amount)}</td>
                </tr>
              ))}
              <tr className="income-exp-report-subtotal">
                <td className="income-exp-report-subtotal-label">Revenue subtotal</td>
                <td className="journal-list-amount">{formatReportCurrency(report.total_revenue)}</td>
              </tr>
            </tbody>
          </table>

          <h3>Expense accounts</h3>
          <table className="journal-entry-list income-exp-report-table">
            <thead>
              <tr>
                <th scope="col">Account</th>
                <th className="journal-list-amount" scope="col">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {report.expense_accounts.map((row) => (
                <tr key={row.account_id}>
                  <td>
                    {row.account_name}
                    {!row.is_active && <span className="muted"> (inactive)</span>}
                  </td>
                  <td className="journal-list-amount">{formatReportCurrency(row.amount)}</td>
                </tr>
              ))}
              <tr className="income-exp-report-subtotal">
                <td className="income-exp-report-subtotal-label">Expense subtotal</td>
                <td className="journal-list-amount">{formatReportCurrency(report.total_expense)}</td>
              </tr>
            </tbody>
          </table>

          <div className="income-exp-report-net" role="region" aria-label="Net income">
            <span className="income-exp-report-net-label">Net income</span>
            <span className="income-exp-report-net-amount journal-list-amount">
              {formatReportCurrency(report.net_income)}
            </span>
          </div>

          <div className="income-exp-report-export-bar form-actions-inline">
            <a
              className="button-secondary income-exp-report-export-btn"
              href={incomeExpenseExportUrl("csv", buildParams())}
              download
            >
              Export CSV
            </a>
            <a
              className="button-secondary income-exp-report-export-btn"
              href={incomeExpenseExportUrl("pdf", buildParams())}
              download
            >
              Export PDF
            </a>
          </div>
        </div>
      )}
    </section>
  );
}
