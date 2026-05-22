import { useEffect, useRef } from "react";

import { isNewChord } from "../lib/keyboardChords";

export type AccrualPlanDialogView = "form" | "preview";

export interface AccrualPlanModalShortcutOptions {
  createDialogOpen: boolean;
  createDialogView: AccrualPlanDialogView;
  editDialogOpen: boolean;
  editDialogView: AccrualPlanDialogView;
  viewDialogOpen: boolean;
  canSubmitCreate: boolean;
  canSubmitEdit: boolean;
  createSubmitting: boolean;
  editSubmitting: boolean;
  onCreateSave: () => void;
  onEditSave: () => void;
  onCreateClose: () => void;
  onEditClose: () => void;
  onViewClose: () => void;
  onCreateReturnToForm: () => void;
  onEditReturnToForm: () => void;
  /** Ctrl/Cmd+N on the list when no modal is open. */
  onNewPlan?: () => void;
}

/**
 * Accrual plan list and create/edit/view modals:
 * - Ctrl/Cmd+N: new plan on list when no modal is open
 * - Esc: always close the open modal
 * - Ctrl/Cmd+S: preview (form) or save (preview) — active while any plan modal is open
 * - Ctrl/Cmd+Shift+D: return from preview to form (preview step only)
 */
export function useAccrualPlanModalShortcuts(opts: AccrualPlanModalShortcutOptions): void {
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const o = optsRef.current;
      const modalOpen = o.createDialogOpen || o.editDialogOpen || o.viewDialogOpen;

      if (!modalOpen && isNewChord(e) && o.onNewPlan) {
        e.preventDefault();
        o.onNewPlan();
        return;
      }

      if (!modalOpen) {
        return;
      }

      const saveChord =
        (e.key === "s" || e.key === "S") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
      const previewRevertChord =
        (e.key === "d" || e.key === "D") && (e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey;

      if (e.key === "Escape") {
        if (o.viewDialogOpen) {
          e.preventDefault();
          o.onViewClose();
          return;
        }
        if (o.editDialogOpen) {
          e.preventDefault();
          o.onEditClose();
          return;
        }
        if (o.createDialogOpen) {
          e.preventDefault();
          o.onCreateClose();
          return;
        }
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

      if (previewRevertChord) {
        if (o.createDialogOpen && o.createDialogView === "preview" && !o.createSubmitting) {
          e.preventDefault();
          o.onCreateReturnToForm();
        } else if (o.editDialogOpen && o.editDialogView === "preview" && !o.editSubmitting) {
          e.preventDefault();
          o.onEditReturnToForm();
        }
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}
