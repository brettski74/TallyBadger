export type PartySortDirection = "asc" | "desc";

export interface PartySortKey {
  field: string;
  direction: PartySortDirection;
}

export const PARTY_REGISTER_SORT_FIELDS = {
  name: "name",
  role: "role",
  subtype: "subtype",
  isActive: "is_active",
} as const;

export type PartyRegisterSortField =
  (typeof PARTY_REGISTER_SORT_FIELDS)[keyof typeof PARTY_REGISTER_SORT_FIELDS];

export function primarySortKey(keys: PartySortKey[]): PartySortKey | null {
  return keys.length > 0 ? keys[0] : null;
}

export function toSortParams(keys: PartySortKey[]): string[] {
  return keys.map(({ field, direction }) => `${field}:${direction}`);
}

export function cycleSortKeys(current: PartySortKey[], clickedField: string): PartySortKey[] {
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
