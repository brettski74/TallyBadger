import { FormEvent, useCallback, useState } from "react";

import {
  type BalanceSheetPreset,
  type FetchBalanceSheetParams,
  type BalanceSheetReport,
  balanceSheetExportUrl,
  fetchBalanceSheetReport,
} from "../api/balanceSheetReport";

function localCalendarTodayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

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

type DateMode = "custom" | BalanceSheetPreset;

export function BalanceSheetReportSection() {
  const [dateMode, setDateMode] = useState<DateMode>("today");
  const [customAsOfDate, setCustomAsOfDate] = useState("");
  const [excludeRequiresReview, setExcludeRequiresReview] = useState(false);
  const [report, setReport] = useState<BalanceSheetReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildParams = useCallback((): FetchBalanceSheetParams => {
    const base = { excludeRequiresReview };
    if (dateMode === "custom") {
      return { ...base, asOfDate: customAsOfDate };
    }
    return { ...base, preset: dateMode, presetAnchorDate: localCalendarTodayIso() };
  }, [customAsOfDate, dateMode, excludeRequiresReview]);

  async function runReport(event?: FormEvent) {
    event?.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (dateMode === "custom" && !customAsOfDate) {
        throw new Error("Choose an as-of date for a custom report.");
      }
      const data = await fetchBalanceSheetReport(buildParams());
      setReport(data);
    } catch (err) {
      setReport(null);
      setError(err instanceof Error ? err.message : "Failed to load report");
    } finally {
      setLoading(false);
    }
  }

  function renderSection(section: BalanceSheetReport["assets"]): JSX.Element {
    return (
      <>
        <h3>{section.label}</h3>
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
            {section.accounts.map((row, idx) => (
              <tr key={`${section.section}-${row.account_id ?? "computed"}-${idx}`}>
                <td>
                  {row.account_name}
                  {row.is_computed && <span className="muted"> (computed)</span>}
                  {row.is_active === false && <span className="muted"> (inactive)</span>}
                </td>
                <td className="journal-list-amount">{formatReportCurrency(row.amount)}</td>
              </tr>
            ))}
            <tr className="income-exp-report-subtotal">
              <td className="income-exp-report-subtotal-label">{section.label} total</td>
              <td className="journal-list-amount">{formatReportCurrency(section.total)}</td>
            </tr>
          </tbody>
        </table>
      </>
    );
  }

  return (
    <section className="card journal-card-wide" aria-labelledby="balance-sheet-heading">
      <h2 id="balance-sheet-heading">Balance sheet report</h2>
      <p className="muted">Point-in-time assets, liabilities, and equity with a balancing check.</p>

      <form className="journal-filters" onSubmit={(e) => void runReport(e)}>
        <div>
          <label htmlFor="balance-sheet-date-mode">As of</label>
          <select
            id="balance-sheet-date-mode"
            value={dateMode}
            onChange={(e) => setDateMode(e.target.value as DateMode)}
          >
            <option value="today">Today</option>
            <option value="prior_year_end">Prior year end</option>
            <option value="custom">Custom date</option>
          </select>
        </div>
        {dateMode === "custom" && (
          <div>
            <label htmlFor="balance-sheet-custom-date">Date</label>
            <input
              id="balance-sheet-custom-date"
              type="date"
              value={customAsOfDate}
              onChange={(e) => setCustomAsOfDate(e.target.value)}
            />
          </div>
        )}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={excludeRequiresReview}
            onChange={(e) => setExcludeRequiresReview(e.target.checked)}
          />
          Exclude entries marked requires review
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
            <strong>As of:</strong> {report.period.as_of_date}
            {report.preset && (
              <span className="muted">
                {" "}
                (preset: {report.preset.replace(/_/g, " ")})
              </span>
            )}
          </p>

          {renderSection(report.assets)}
          {renderSection(report.liabilities)}
          {renderSection(report.equity)}

          <h3>Balance check</h3>
          <div className="balance-sheet-check" role="region" aria-label="Balance check">
            <span>Assets total</span>
            <span className="journal-list-amount">{formatReportCurrency(report.balance_check.assets_total)}</span>
            <span>Liabilities + equity</span>
            <span className="journal-list-amount">
              {formatReportCurrency(report.balance_check.liabilities_plus_equity)}
            </span>
            <span>Balance</span>
            <span className="journal-list-amount">{formatReportCurrency(report.balance_check.difference)}</span>
          </div>

          <div className="income-exp-report-export-bar form-actions-inline">
            <a
              className="button-secondary income-exp-report-export-btn"
              href={balanceSheetExportUrl("csv", buildParams())}
              download
            >
              Export CSV
            </a>
            <a
              className="button-secondary income-exp-report-export-btn"
              href={balanceSheetExportUrl("pdf", buildParams())}
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
