import type { KeyboardEvent } from "react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

const MAX_OPTIONS = 20;

/** Case-insensitive prefix match, deduped, sorted, capped. */
export function filterSubtypeOptions(query: string, suggestions: readonly string[]): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const s of suggestions) {
    const low = s.toLowerCase();
    if (!low.startsWith(q)) continue;
    if (seen.has(low)) continue;
    seen.add(low);
    out.push(s);
  }
  out.sort((a, b) => a.localeCompare(b));
  return out.slice(0, MAX_OPTIONS);
}

export type SubtypeComboboxProps = {
  "aria-label": string;
  value: string;
  onChange: (value: string) => void;
  suggestions: readonly string[];
  placeholder?: string;
};

/**
 * Free-text field with prefix-matched suggestions (not native HTML datalist).
 * Enter, Tab, or ArrowRight accepts the highlighted row; ArrowUp/Down moves highlight;
 * Escape closes the list until the user edits again (any input event).
 */
export function SubtypeCombobox({
  "aria-label": ariaLabel,
  value,
  onChange,
  suggestions,
  placeholder,
}: SubtypeComboboxProps) {
  const listboxId = useId();
  const [highlightIndex, setHighlightIndex] = useState(0);
  /** After accept or Escape, hide list until the user types/pastes (onInput). */
  const [panelSuppressed, setPanelSuppressed] = useState(false);
  const [focused, setFocused] = useState(false);
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const filtered = useMemo(() => filterSubtypeOptions(value, suggestions), [value, suggestions]);

  useEffect(() => {
    setHighlightIndex(0);
  }, [filtered]);

  function clearBlurTimer() {
    if (blurTimer.current != null) {
      clearTimeout(blurTimer.current);
      blurTimer.current = null;
    }
  }

  function applyOption(opt: string) {
    clearBlurTimer();
    onChange(opt);
    setPanelSuppressed(true);
  }

  const showPanel = focused && filtered.length > 0 && !panelSuppressed;

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (!showPanel) {
      if (e.key === "Escape") {
        e.preventDefault();
        setPanelSuppressed(true);
      }
      return;
    }

    const choice = filtered[highlightIndex];
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((i) => (i + 1) % filtered.length);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((i) => (i - 1 + filtered.length) % filtered.length);
      return;
    }
    if (e.key === "Enter" || e.key === "ArrowRight") {
      if (choice != null) {
        e.preventDefault();
        e.stopPropagation();
        applyOption(choice);
      }
      return;
    }
    if (e.key === "Tab" && !e.shiftKey && choice != null) {
      applyOption(choice);
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      setPanelSuppressed(true);
    }
  }

  return (
    <div className="subtype-combobox-wrap">
      <input
        type="text"
        autoComplete="off"
        spellCheck={false}
        aria-label={ariaLabel}
        aria-autocomplete="list"
        aria-expanded={showPanel}
        aria-controls={showPanel ? listboxId : undefined}
        role="combobox"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onInput={() => setPanelSuppressed(false)}
        onKeyDown={handleKeyDown}
        onFocus={() => {
          clearBlurTimer();
          setFocused(true);
        }}
        onBlur={() => {
          clearBlurTimer();
          blurTimer.current = setTimeout(() => {
            setFocused(false);
            blurTimer.current = null;
          }, 150);
        }}
      />
      {showPanel ? (
        <ul id={listboxId} className="subtype-combobox-list" role="listbox">
          {filtered.map((opt, i) => (
            <li
              key={opt}
              role="option"
              aria-selected={i === highlightIndex}
              className={`subtype-combobox-option${i === highlightIndex ? " subtype-combobox-option-active" : ""}`}
              onMouseDown={(e) => {
                e.preventDefault();
                applyOption(opt);
              }}
              onMouseEnter={() => setHighlightIndex(i)}
            >
              {opt}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
