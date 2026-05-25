export type SortDirection = "asc" | "desc";

export interface SortKey {
  field: string;
  direction: SortDirection;
}

export function primarySortKey(keys: SortKey[]): SortKey | null {
  return keys.length > 0 ? keys[0] : null;
}

export function toSortParams(keys: SortKey[]): string[] {
  return keys.map(({ field, direction }) => `${field}:${direction}`);
}

export function cycleSortKeys(current: SortKey[], clickedField: string): SortKey[] {
  const index = current.findIndex((key) => key.field === clickedField);
  const isPrimary = index === 0;

  if (!isPrimary) {
    const withoutClicked = current.filter((key) => key.field !== clickedField);
    return [{ field: clickedField, direction: "asc" }, ...withoutClicked];
  }

  const primary = current[0];
  if (primary.direction === "asc") {
    return [{ field: clickedField, direction: "desc" }, ...current.slice(1)];
  }

  return current.slice(1);
}

export function sameSortKeys(a: SortKey[], b: SortKey[]): boolean {
  if (a.length !== b.length) {
    return false;
  }
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].field !== b[i].field || a[i].direction !== b[i].direction) {
      return false;
    }
  }
  return true;
}
