import { useEffect, useRef, useState } from "react";

export interface JournalFilterMultiOption<TId extends string | number = number> {
  id: TId;
  name: string;
}

function sortSelectedIds<TId extends string | number>(ids: TId[]): TId[] {
  const copy = [...ids];
  if (copy.length === 0) {
    return copy;
  }
  if (typeof copy[0] === "number") {
    return copy.sort((a, b) => (a as number) - (b as number));
  }
  return copy.sort((a, b) => String(a).localeCompare(String(b)));
}

export function JournalFilterMultiDropdown<TId extends string | number = number>({
  label,
  ariaFilterLabel,
  options,
  selectedIds,
  onIdsChange,
}: {
  label: string;
  ariaFilterLabel: string;
  options: JournalFilterMultiOption<TId>[];
  selectedIds: TId[];
  onIdsChange: (ids: TId[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const summaryText = selectedIds.length === 0 ? "All" : `${selectedIds.length} selected`;

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

  function toggle(id: TId) {
    const set = new Set(selectedIds);
    if (set.has(id)) {
      set.delete(id);
    } else {
      set.add(id);
    }
    onIdsChange(sortSelectedIds([...set]));
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
            <label key={String(o.id)} className="journal-filter-menu-option">
              <input type="checkbox" checked={selectedIds.includes(o.id)} onChange={() => toggle(o.id)} />
              <span>{o.name}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
