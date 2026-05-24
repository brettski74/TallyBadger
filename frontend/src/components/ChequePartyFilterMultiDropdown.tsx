import { useEffect, useRef, useState } from "react";

import type { ChequeFilterOption } from "../api/cheques";

export type ChequePartyFilterId = number | null;

function partyFilterKey(id: ChequePartyFilterId): string {
  return id === null ? "null" : String(id);
}

function sortPartyFilters(ids: ChequePartyFilterId[]): ChequePartyFilterId[] {
  return [...ids].sort((a, b) => {
    if (a === null && b === null) {
      return 0;
    }
    if (a === null) {
      return -1;
    }
    if (b === null) {
      return 1;
    }
    return a - b;
  });
}

export function ChequePartyFilterMultiDropdown({
  label,
  ariaFilterLabel,
  options,
  selectedIds,
  onIdsChange,
}: {
  label: string;
  ariaFilterLabel: string;
  options: ChequeFilterOption[];
  selectedIds: ChequePartyFilterId[];
  onIdsChange: (ids: ChequePartyFilterId[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const summaryText =
    selectedIds.length === 0 ? "All" : `${selectedIds.length} selected`;

  useEffect(() => {
    if (!open) {
      return;
    }
    function handlePointerDown(event: PointerEvent) {
      const root = rootRef.current;
      if (root && !root.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function toggle(id: ChequePartyFilterId) {
    const set = new Set(selectedIds.map(partyFilterKey));
    const key = partyFilterKey(id);
    if (set.has(key)) {
      set.delete(key);
    } else {
      set.add(key);
    }
    const next = options
      .filter((o) => set.has(partyFilterKey(o.id)))
      .map((o) => o.id);
    onIdsChange(sortPartyFilters(next));
  }

  return (
    <div ref={rootRef} className="journal-filter-slot journal-filter-slot-multi">
      <button
        type="button"
        className="journal-filter-multi-trigger"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaFilterLabel}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="journal-filter-inline-label">{label}</span>
        <span className="journal-filter-multi-value">{summaryText}</span>
      </button>
      {open && (
        <div className="journal-filter-details-menu" role="listbox" aria-label={ariaFilterLabel}>
          {selectedIds.length > 0 && (
            <button
              type="button"
              className="journal-filter-clear"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onIdsChange([]);
              }}
            >
              Clear selection
            </button>
          )}
          {options.map((o) => (
            <label key={partyFilterKey(o.id)} className="journal-filter-menu-option">
              <input
                type="checkbox"
                checked={selectedIds.some((id) => id === o.id)}
                onChange={() => toggle(o.id)}
              />
              <span>{o.name}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
