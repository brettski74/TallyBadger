import type { PartyActiveFilter, PartyListParams, PartyRole } from "../api/parties";
import type { PartySortKey } from "./partyRegisterSort";
import { toSortParams } from "./partyRegisterSort";

export function partyListParamsFromRegisterState(state: {
  filterName: string;
  activeFilter: PartyActiveFilter;
  selectedRoles: PartyRole[];
  selectedSubtypes: string[];
  sortKeys: PartySortKey[];
}): PartyListParams {
  const params: PartyListParams = {
    sort: state.sortKeys.length > 0 ? toSortParams(state.sortKeys) : undefined,
  };
  const name = state.filterName.trim();
  if (name) {
    params.name = name;
  }
  if (state.activeFilter === "active") {
    params.is_active = true;
  } else if (state.activeFilter === "inactive") {
    params.is_active = false;
  }
  if (state.selectedRoles.length > 0) {
    params.roles = state.selectedRoles;
  }
  if (state.selectedSubtypes.length > 0) {
    params.subtypes = state.selectedSubtypes;
  }
  return params;
}
