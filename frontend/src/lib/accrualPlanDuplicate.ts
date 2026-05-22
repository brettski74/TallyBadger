const FISCAL_PAIR_RE = /(\d{4})\/(\d{1,4})/g;
const STANDALONE_YEAR_RE = /(?:19|20)\d{2}/g;

function resolveEndCalendarYear(startYear: number, endSegment: string): number {
  if (/^(?:19|20)\d{2}$/.test(endSegment)) {
    return Number.parseInt(endSegment, 10);
  }
  const nextYear = startYear + 1;
  if (String(nextYear).endsWith(endSegment)) {
    return nextYear;
  }
  for (let y = startYear; y < startYear + 100; y += 1) {
    if (String(y).endsWith(endSegment)) {
      return y;
    }
  }
  return nextYear;
}

/** Minimal-digit end segment for a fiscal-year pair label (e.g. 2029/30). */
export function abbreviateFiscalYearEndSegment(startYear: number, endCalendarYear: number): string {
  const full = String(endCalendarYear);
  if (endCalendarYear < 1900 || endCalendarYear >= 2100) {
    return full;
  }
  for (let len = 1; len < 4; len += 1) {
    const suffix = full.slice(-len);
    if (suffix === "0") {
      continue;
    }
    if (resolveEndCalendarYear(startYear, suffix) === endCalendarYear) {
      return suffix;
    }
  }
  return full;
}

function findRightmostFiscalPair(name: string): { index: number; length: number; startYear: number; endSegment: string } | null {
  let last: RegExpExecArray | null = null;
  FISCAL_PAIR_RE.lastIndex = 0;
  let match = FISCAL_PAIR_RE.exec(name);
  while (match) {
    last = match;
    match = FISCAL_PAIR_RE.exec(name);
  }
  if (!last || last.index === undefined) {
    return null;
  }
  return {
    index: last.index,
    length: last[0].length,
    startYear: Number.parseInt(last[1], 10),
    endSegment: last[2],
  };
}

function findRightmostStandaloneYear(name: string, excludeStart: number, excludeEnd: number): { index: number; length: number; year: number } | null {
  let last: { index: number; length: number; year: number } | null = null;
  STANDALONE_YEAR_RE.lastIndex = 0;
  let match = STANDALONE_YEAR_RE.exec(name);
  while (match) {
    const idx = match.index;
    const overlapsPair =
      excludeStart >= 0 && idx >= excludeStart && idx + match[0].length <= excludeEnd;
    if (!overlapsPair) {
      last = { index: idx, length: match[0].length, year: Number.parseInt(match[0], 10) };
    }
    match = STANDALONE_YEAR_RE.exec(name);
  }
  return last;
}

function advanceFiscalPairInName(name: string, pair: NonNullable<ReturnType<typeof findRightmostFiscalPair>>): string {
  const endCal = resolveEndCalendarYear(pair.startYear, pair.endSegment);
  const newStart = pair.startYear + 1;
  const newEndCal = endCal + 1;
  const endWasFullYear = /^(?:19|20)\d{2}$/.test(pair.endSegment);
  const endPart = endWasFullYear
    ? String(newEndCal)
    : abbreviateFiscalYearEndSegment(newStart, newEndCal);
  const replacement = `${newStart}/${endPart}`;
  return name.slice(0, pair.index) + replacement + name.slice(pair.index + pair.length);
}

function advanceStandaloneYearInName(
  name: string,
  yearMatch: NonNullable<ReturnType<typeof findRightmostStandaloneYear>>,
): string {
  const replacement = String(yearMatch.year + 1);
  return name.slice(0, yearMatch.index) + replacement + name.slice(yearMatch.index + yearMatch.length);
}

function isUnique(name: string, existingNames: ReadonlySet<string>): boolean {
  return !existingNames.has(name);
}

function withCopySuffix(sourceName: string, existingNames: ReadonlySet<string>): string {
  const base = `${sourceName} - Copy`;
  if (isUnique(base, existingNames)) {
    return base;
  }
  for (let n = 1; n < 10_000; n += 1) {
    const candidate = `${sourceName} - Copy (${n})`;
    if (isUnique(candidate, existingNames)) {
      return candidate;
    }
  }
  throw new Error("Could not generate a unique accrual plan name");
}

/**
 * Propose a unique plan name when duplicating, per issue #182 naming rules.
 */
export function proposeDuplicateAccrualPlanName(
  sourceName: string,
  existingNames: Iterable<string>,
): string {
  const taken = new Set(existingNames);

  const pair = findRightmostFiscalPair(sourceName);
  const pairSpanStart = pair?.index ?? -1;
  const pairSpanEnd = pair ? pair.index + pair.length : -1;

  if (pair) {
    const advanced = advanceFiscalPairInName(sourceName, pair);
    if (isUnique(advanced, taken)) {
      return advanced;
    }
  }

  const standalone = findRightmostStandaloneYear(sourceName, pairSpanStart, pairSpanEnd);
  if (standalone) {
    const advanced = advanceStandaloneYearInName(sourceName, standalone);
    if (isUnique(advanced, taken)) {
      return advanced;
    }
  }

  return withCopySuffix(sourceName, taken);
}

/**
 * Shift ISO dates forward by one calendar year; invalid days clamp to month end (e.g. 29 Feb → 28 Feb).
 */
export function shiftAccrualPlanDatesByOneYear(
  start: string,
  end: string,
): { start: string; end: string } {
  return {
    start: addCalendarYears(start, 1),
    end: addCalendarYears(end, 1),
  };
}

function addCalendarYears(dateStr: string, years: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) {
    throw new Error(`Invalid date: ${dateStr}`);
  }
  const y = Number.parseInt(match[1], 10);
  const m = Number.parseInt(match[2], 10);
  const d = Number.parseInt(match[3], 10);
  const targetYear = y + years;
  const lastDayOfMonth = new Date(targetYear, m, 0).getDate();
  const day = Math.min(d, lastDayOfMonth);
  return `${targetYear}-${String(m).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
