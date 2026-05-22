import { useEffect, useRef } from "react";

import { isNewChord } from "../lib/keyboardChords";

export type ChequeCreateDialogView = "form" | "preview";

export interface ChequeCreateModalShortcutOptions {
  createDialogOpen: boolean;
  createDialogView: ChequeCreateDialogView;
  canSubmitCreate: boolean;
  createSubmitting: boolean;
  newShortcutActive: boolean;
  onSave: () => void;
  onClose: () => void;
  onReturnToForm: () => void;
  onRevertForm: () => void;
  onNewCheque: () => void;
}

/**
 * Cheque create modal:
 * - Esc: close without save
 * - Ctrl/Cmd+S: preview (form) or submit (preview / single)
 * - Ctrl/Cmd+Shift+D: preview → form; form → revert fields toward last stable state
 * - Ctrl/Cmd+Shift+N: new cheque when dialog is closed (`newShortcutActive`)
 */
export function useChequeCreateModalShortcuts(opts: ChequeCreateModalShortcutOptions): void {
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const o = optsRef.current;

      if (isNewChord(e) && !o.createDialogOpen && o.newShortcutActive) {
        e.preventDefault();
        o.onNewCheque();
        return;
      }

      if (!o.createDialogOpen) {
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
        if (!o.createSubmitting && o.canSubmitCreate) {
          e.preventDefault();
          o.onSave();
        }
        return;
      }

      if (revertChord) {
        if (o.createSubmitting) {
          return;
        }
        e.preventDefault();
        if (o.createDialogView === "preview") {
          o.onReturnToForm();
        } else {
          o.onRevertForm();
        }
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}
