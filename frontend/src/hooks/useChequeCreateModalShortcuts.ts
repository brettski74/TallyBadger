import { useEffect, useRef } from "react";

import { isNewChord } from "../lib/keyboardChords";

export type ChequeCreateDialogView = "form" | "preview";

export interface ChequeModalShortcutOptions {
  createDialogOpen: boolean;
  createDialogView: ChequeCreateDialogView;
  editDialogOpen: boolean;
  viewDialogOpen: boolean;
  canSubmitCreate: boolean;
  canSubmitEdit: boolean;
  createSubmitting: boolean;
  editSubmitting: boolean;
  newShortcutActive: boolean;
  onCreateSave: () => void;
  onEditSave: () => void;
  onCreateClose: () => void;
  onEditClose: () => void;
  onViewClose: () => void;
  onCreateReturnToForm: () => void;
  onCreateRevertForm: () => void;
  onEditRevertForm: () => void;
  onNewCheque: () => void;
}

/**
 * Cheque create / edit / view modals:
 * - Esc: close without save (silent discard)
 * - Ctrl/Cmd+S: preview or submit (create); save (edit)
 * - Ctrl/Cmd+Shift+D: create preview → form; create/edit form → revert toward baseline
 * - Ctrl/Cmd+Shift+N: new cheque when no modal is open (`newShortcutActive`)
 */
export function useChequeCreateModalShortcuts(opts: ChequeModalShortcutOptions): void {
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const o = optsRef.current;
      const modalOpen = o.createDialogOpen || o.editDialogOpen || o.viewDialogOpen;

      if (isNewChord(e) && !modalOpen && o.newShortcutActive) {
        e.preventDefault();
        o.onNewCheque();
        return;
      }

      if (!modalOpen) {
        return;
      }

      const saveChord =
        (e.key === "s" || e.key === "S") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
      const revertChord =
        (e.key === "d" || e.key === "D") && (e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey;

      if (e.key === "Escape") {
        e.preventDefault();
        if (o.viewDialogOpen) {
          o.onViewClose();
        } else if (o.editDialogOpen) {
          o.onEditClose();
        } else if (o.createDialogOpen) {
          o.onCreateClose();
        }
        return;
      }

      if (saveChord) {
        if (o.createDialogOpen && !o.createSubmitting && o.canSubmitCreate) {
          e.preventDefault();
          o.onCreateSave();
        } else if (o.editDialogOpen && !o.editSubmitting && o.canSubmitEdit) {
          e.preventDefault();
          o.onEditSave();
        }
        return;
      }

      if (revertChord) {
        if (o.createSubmitting || o.editSubmitting || o.viewDialogOpen) {
          return;
        }
        e.preventDefault();
        if (o.createDialogOpen) {
          if (o.createDialogView === "preview") {
            o.onCreateReturnToForm();
          } else {
            o.onCreateRevertForm();
          }
          return;
        }
        if (o.editDialogOpen) {
          o.onEditRevertForm();
        }
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}
