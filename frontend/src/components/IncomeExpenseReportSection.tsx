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
          <a
            className="button-secondary"
            href={incomeExpenseExportUrl("csv", buildParams())}
            download
          >
            Export CSV
          </a>
          <a className="button-secondary" href={incomeExpenseExportUrl("pdf", buildParams())} download>
            Export PDF
          </a>
        </div>
      </form>

      {error && <p role="alert">{error}</p>}

      {report && (
        <div className="report-output">
          <p>
            <strong>Period:</strong> {report.period.start_date} to {report.period.end_date}
            {report.preset && (
              <span className="muted">
                {" "}
                (preset: {report.preset.replace(/_/g, " ")})
              </span>
            )}
          </p>
          <ul className="banner-info">
            <li>
              <strong>Total revenue</strong> {report.total_revenue}
            </li>
            <li>
              <strong>Total expense</strong> {report.total_expense}
            </li>
            <li>
              <strong>Net income</strong> {report.net_income}
            </li>
            <li className="muted">Currency: {report.currency_label}</li>
          </ul>

          <h3>Revenue accounts</h3>
          <table className="journal-entry-list">
            <thead>
              <tr>
                <th scope="col">Account</th>
                <th scope="col">Amount</th>
              </tr>
            </thead>
            <tbody>
              {report.revenue_accounts.map((row) => (
                <tr key={row.account_id}>
                  <td>
                    {row.account_name}
                    {!row.is_active && <span className="muted"> (inactive)</span>}
                  </td>
                  <td>{row.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Expense accounts</h3>
          <table className="journal-entry-list">
            <thead>
              <tr>
                <th scope="col">Account</th>
                <th scope="col">Amount</th>
              </tr>
            </thead>
            <tbody>
              {report.expense_accounts.map((row) => (
                <tr key={row.account_id}>
                  <td>
                    {row.account_name}
                    {!row.is_active && <span className="muted"> (inactive)</span>}
                  </td>
                  <td>{row.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
