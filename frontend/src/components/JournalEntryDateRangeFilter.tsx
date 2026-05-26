import { useCallback, useEffect, useRef, useState } from "react";

import { resolveDateExpression } from "../api/dateRange";
import {
  JOURNAL_QUICK_RANGE_CUSTOM,
  JOURNAL_QUICK_RANGE_OPTIONS,
  matchQuickRangeId,
  type JournalQuickRangeId,
} from "../lib/journalEntryDateRangeCatalog";

export interface JournalEntryDateRangeValue {
  fromDate: string;
  toDate: string;
}

interface JournalEntryDateRangeFilterProps {
  value: JournalEntryDateRangeValue;
  onChange: (patch: Partial<JournalEntryDateRangeValue>) => void;
}

function formatDisplayDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  if (!year || !month || !day) {
    return isoDate;
  }
  return `${day}/${month}/${year}`;
}

export function JournalEntryDateRangeFilter({
  value,
  onChange,
}: JournalEntryDateRangeFilterProps) {
  const [quickRangeId, setQuickRangeId] = useState<JournalQuickRangeId>("custom");
  const [fromFocused, setFromFocused] = useState(false);
  const [toFocused, setToFocused] = useState(false);
  const [fromDisplay, setFromDisplay] = useState("");
  const [toDisplay, setToDisplay] = useState("");
  const [fromResolveError, setFromResolveError] = useState<string | null>(null);
  const [toResolveError, setToResolveError] = useState<string | null>(null);
  const [fromResolving, setFromResolving] = useState(false);
  const [toResolving, setToResolving] = useState(false);
  const suppressQuickRangeSyncRef = useRef(false);

  const runReverseMatch = useCallback(() => {
    if (fromFocused || toFocused || suppressQuickRangeSyncRef.current) {
      return;
    }
    setQuickRangeId(matchQuickRangeId(value.fromDate, value.toDate));
  }, [fromFocused, toFocused, value.fromDate, value.toDate]);

  useEffect(() => {
    runReverseMatch();
  }, [runReverseMatch]);

  const resolveBound = useCallback(async (expr: string, bound: "from" | "to") => {
    const trimmed = expr.trim();
    if (!trimmed) {
      if (bound === "from") {
        setFromDisplay("");
        setFromResolveError(null);
      } else {
        setToDisplay("");
        setToResolveError(null);
      }
      return;
    }
    if (bound === "from") {
      setFromResolving(true);
      setFromResolveError(null);
    } else {
      setToResolving(true);
      setToResolveError(null);
    }
    try {
      const resolved = await resolveDateExpression(trimmed);
      const formatted = formatDisplayDate(resolved);
      if (bound === "from") {
        setFromDisplay(formatted);
      } else {
        setToDisplay(formatted);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not resolve date";
      if (bound === "from") {
        setFromResolveError(message);
        setFromDisplay("");
      } else {
        setToResolveError(message);
        setToDisplay("");
      }
    } finally {
      if (bound === "from") {
        setFromResolving(false);
      } else {
        setToResolving(false);
      }
    }
  }, []);

  useEffect(() => {
    if (fromFocused) {
      return;
    }
    void resolveBound(value.fromDate, "from");
  }, [fromFocused, value.fromDate, resolveBound]);

  useEffect(() => {
    if (toFocused) {
      return;
    }
    void resolveBound(value.toDate, "to");
  }, [toFocused, value.toDate, resolveBound]);

  function handleQuickRangeChange(nextId: string) {
    if (nextId === "custom") {
      setQuickRangeId("custom");
      return;
    }
    const option = JOURNAL_QUICK_RANGE_OPTIONS.find((row) => row.id === nextId);
    if (!option) {
      return;
    }
    suppressQuickRangeSyncRef.current = true;
    setQuickRangeId(option.id);
    onChange({ fromDate: option.fromExpr, toDate: option.toExpr });
    queueMicrotask(() => {
      suppressQuickRangeSyncRef.current = false;
    });
  }

  return (
    <>
      <label className="journal-filter-slot journal-filter-slot-select">
        <span className="journal-filter-inline-label">Date range</span>
        <select
          className="journal-filter-control"
          aria-label="Quick date range"
          value={quickRangeId}
          onChange={(e) => handleQuickRangeChange(e.target.value)}
        >
          {JOURNAL_QUICK_RANGE_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
          <option value={JOURNAL_QUICK_RANGE_CUSTOM.id}>{JOURNAL_QUICK_RANGE_CUSTOM.label}</option>
        </select>
      </label>
      <label className="journal-filter-slot journal-filter-slot-date">
        <span className="journal-filter-inline-label">From Date</span>
        <input
          className="journal-filter-control"
          aria-label="Filter from date"
          type="text"
          value={fromFocused ? value.fromDate : fromResolving ? "…" : fromDisplay}
          aria-invalid={fromResolveError != null}
          onFocus={() => {
            setFromFocused(true);
            setFromResolveError(null);
          }}
          onBlur={() => {
            setFromFocused(false);
          }}
          onChange={(e) => onChange({ fromDate: e.target.value })}
        />
        {fromResolveError && !fromFocused && (
          <span className="error journal-filter-resolve-error" role="alert">
            {fromResolveError}
          </span>
        )}
      </label>
      <label className="journal-filter-slot journal-filter-slot-date">
        <span className="journal-filter-inline-label">To Date</span>
        <input
          className="journal-filter-control"
          aria-label="Filter to date"
          type="text"
          value={toFocused ? value.toDate : toResolving ? "…" : toDisplay}
          aria-invalid={toResolveError != null}
          onFocus={() => {
            setToFocused(true);
            setToResolveError(null);
          }}
          onBlur={() => {
            setToFocused(false);
          }}
          onChange={(e) => onChange({ toDate: e.target.value })}
        />
        {toResolveError && !toFocused && (
          <span className="error journal-filter-resolve-error" role="alert">
            {toResolveError}
          </span>
        )}
      </label>
    </>
  );
}
