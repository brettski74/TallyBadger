import { useEffect, useRef } from "react";

export interface JournalEntryFormShortcutOptions {
  formActive: boolean;
  canSave: boolean;
  saving: boolean;
  onSave: () => void;
  onRevert: () => void;
  onClose: () => void;
}

/**
 * Full-page journal entry editor (modal-like): focus-independent chords per STYLE.md.
 */
export function useJournalEntryFormShortcuts(opts: JournalEntryFormShortcutOptions): void {
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const o = optsRef.current;
      if (!o.formActive) {
        return;
      }

      const saveChord =
        (e.key === "s" || e.key === "S") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
      const revertChord =
        (e.key === "d" || e.key === "D") && (e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey;

      if (e.key === "Escape") {
        e.preventDefault();
        o.onClose();
        return;
      }

      if (saveChord) {
        if (!o.saving && o.canSave) {
          e.preventDefault();
          o.onSave();
        }
        return;
      }

      if (revertChord) {
        if (o.saving) {
          return;
        }
        e.preventDefault();
        o.onRevert();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}

function isNewChord(e: KeyboardEvent): boolean {
  return (e.key === "n" || e.key === "N") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
}

export function useJournalListNewShortcut(opts: {
  listActive: boolean;
  onNew: () => void;
}): void {
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const o = optsRef.current;
      if (!o.listActive || !isNewChord(e)) {
        return;
      }
      e.preventDefault();
      o.onNew();
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}
