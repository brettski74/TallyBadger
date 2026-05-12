import { type RefObject, useEffect, useRef } from "react";

export interface FormSaveDiscardShortcutOptions {
  createFormRef: RefObject<HTMLFormElement | null>;
  editFormRef: RefObject<HTMLFormElement | null>;
  editingPartyId: number | null;
  canSubmitCreate: boolean;
  canSubmitEdit: boolean;
  createSubmitting: boolean;
  editSubmitting: boolean;
  requestCreateSubmit: () => void;
  requestEditSubmit: () => void;
  requestEditDiscard: () => void;
}

/**
 * Save: Ctrl/Cmd+S when focus is inside the owning form (create when not editing; edit when editing).
 * Discard: Ctrl/Cmd+Shift+D when focus is inside the edit form while editing.
 */
export function useFormSaveDiscardShortcuts(opts: FormSaveDiscardShortcutOptions): void {
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const o = optsRef.current;
      const target = e.target;
      if (!(target instanceof Node)) {
        return;
      }

      const inCreate = o.createFormRef.current?.contains(target) ?? false;
      const inEdit = o.editFormRef.current?.contains(target) ?? false;

      const saveChord =
        (e.key === "s" || e.key === "S") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;

      const discardChord =
        (e.key === "d" || e.key === "D") && (e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey;

      if (saveChord) {
        if (o.editingPartyId != null && inEdit) {
          if (!o.editSubmitting && o.canSubmitEdit) {
            e.preventDefault();
            o.requestEditSubmit();
          }
        } else if (o.editingPartyId == null && inCreate) {
          if (!o.createSubmitting && o.canSubmitCreate) {
            e.preventDefault();
            o.requestCreateSubmit();
          }
        }
        return;
      }

      if (discardChord && o.editingPartyId != null && inEdit && !o.editSubmitting) {
        e.preventDefault();
        o.requestEditDiscard();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}
