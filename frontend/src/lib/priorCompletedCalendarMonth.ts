/** First and last ISO dates (YYYY-MM-DD) of the most recently completed calendar month in local time. */
export function priorCompletedCalendarMonthRange(
  now: Date = new Date(),
): { startDate: string; endDate: string } {
  const year = now.getFullYear();
  const month = now.getMonth();
  const priorEnd = new Date(year, month, 0);
  const priorStart = new Date(priorEnd.getFullYear(), priorEnd.getMonth(), 1);
  const fmt = (d: Date) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  };
  return { startDate: fmt(priorStart), endDate: fmt(priorEnd) };
}
