import type { KeyboardEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

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

/** Suffix to show after `typed` to complete to `canonical` (canonical casing). */
export function subtypeCompletionSuffix(typed: string, canonical: string): string {
  const t = typed;
  const c = canonical;
  if (!c.toLowerCase().startsWith(t.toLowerCase())) return "";
  if (t.length >= c.length) return "";
  return c.slice(t.length);
}

export type SubtypeComboboxProps = {
  "aria-label": string;
  value: string;
  onChange: (value: string) => void;
  suggestions: readonly string[];
  placeholder?: string;
};

/**
 * Subtype text field with **inline ghost completion** (dimmed suffix), not a dropdown.
 * Arrow Down/Up cycles when several matches share the same prefix; Enter, Tab, or
 * Right Arrow accepts the offered completion; Escape hides the ghost until you edit again.
 */
export function SubtypeCombobox({
  "aria-label": ariaLabel,
  value,
  onChange,
  suggestions,
  placeholder,
}: SubtypeComboboxProps) {
  const [pickIndex, setPickIndex] = useState(0);
  /** After accept or Escape, hide ghost until the user types/pastes (onInput). */
  const [ghostSuppressed, setGhostSuppressed] = useState(false);
  const [focused, setFocused] = useState(false);
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const candidates = useMemo(() => filterSubtypeOptions(value, suggestions), [value, suggestions]);

  useEffect(() => {
    setPickIndex(0);
  }, [candidates.join("\0")]);

  const chosen = candidates[pickIndex] ?? "";
  const ghostSuffix =
    focused && !ghostSuppressed && value.length > 0 ? subtypeCompletionSuffix(value, chosen) : "";
  const canNormalizeCase =
    focused &&
    !ghostSuppressed &&
    chosen.length > 0 &&
    value !== chosen &&
    value.toLowerCase() === chosen.toLowerCase();

  function clearBlurTimer() {
    if (blurTimer.current != null) {
      clearTimeout(blurTimer.current);
      blurTimer.current = null;
    }
  }

  function applyCanonical(full: string) {
    clearBlurTimer();
    onChange(full);
    setGhostSuppressed(true);
  }

  function acceptIfOffered() {
    if (ghostSuffix.length > 0) {
      applyCanonical(chosen);
      return true;
    }
    if (canNormalizeCase) {
      applyCanonical(chosen);
      return true;
    }
    return false;
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && candidates.length > 1) {
      e.preventDefault();
      setGhostSuppressed(false);
      setPickIndex((i) => (i + 1) % candidates.length);
      return;
    }
    if (e.key === "ArrowUp" && candidates.length > 1) {
      e.preventDefault();
      setGhostSuppressed(false);
      setPickIndex((i) => (i - 1 + candidates.length) % candidates.length);
      return;
    }
    if (e.key === "Enter" || e.key === "ArrowRight") {
      if (acceptIfOffered()) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (e.key === "Tab" && !e.shiftKey && acceptIfOffered()) {
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      setGhostSuppressed(true);
    }
  }

  const showUnderlay = value.length > 0 && (ghostSuffix.length > 0 || canNormalizeCase);

  return (
    <div className="subtype-ghost-wrap">
      {showUnderlay ? (
        <div className="subtype-ghost-underlay" aria-hidden>
          <span className="subtype-ghost-typed">{value}</span>
          {ghostSuffix ? <span className="subtype-ghost-suffix">{ghostSuffix}</span> : null}
        </div>
      ) : null}
      <input
        type="text"
        autoComplete="off"
        spellCheck={false}
        aria-label={ariaLabel}
        aria-autocomplete="inline"
        placeholder={placeholder}
        value={value}
        className={value.length > 0 ? "subtype-ghost-input" : undefined}
        onChange={(e) => onChange(e.target.value)}
        onInput={() => setGhostSuppressed(false)}
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
    </div>
  );
}
