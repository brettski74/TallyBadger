/** Pure helpers for duplicating cheques from the register (issue #184). */

export function proposeNextChequeNumber(
  cheques: ReadonlyArray<{ cheque_number: number }>,
): number {
  if (cheques.length === 0) {
    return 1;
  }
  let max = 0;
  for (const ch of cheques) {
    if (ch.cheque_number > max) {
      max = ch.cheque_number;
    }
  }
  return max + 1;
}

/**
 * Advance an ISO date by one calendar month, preserving day-of-month when valid
 * and clamping to the last day of the target month (cheque series semantics).
 */
export function addOneCalendarMonth(dateStr: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) {
    throw new Error(`Invalid date: ${dateStr}`);
  }
  const year = Number.parseInt(match[1], 10);
  const month = Number.parseInt(match[2], 10);
  const anchorDay = Number.parseInt(match[3], 10);

  let targetYear = year;
  let targetMonth = month + 1;
  while (targetMonth > 12) {
    targetMonth -= 12;
    targetYear += 1;
  }
  while (targetMonth < 1) {
    targetMonth += 12;
    targetYear -= 1;
  }

  const lastDayOfMonth = new Date(targetYear, targetMonth, 0).getDate();
  const day = Math.min(anchorDay, lastDayOfMonth);
  return `${targetYear}-${String(targetMonth).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
