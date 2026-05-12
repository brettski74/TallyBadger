import { type RefObject, useEffect, useRef } from "react";

export function isTargetAssociatedWithForm(target: Node, form: HTMLFormElement | null): boolean {
  if (!form) {
    return false;
  }
  if (form.contains(target)) {
    return true;
  }
  if (
    target instanceof HTMLInputElement ||
    target instanceof HTMLSelectElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLButtonElement
  ) {
    return target.form === form;
  }
  return false;
}

export interface FormSaveDiscardShortcutOptions {
  createFormRef: RefObject<HTMLFormElement | null>;
  editFormRef: RefObject<HTMLFormElement | null>;
  editingId: number | null;
  /**
   * When true, Ctrl/Cmd+S prefers the create form (inline new row on Accounts).
   * When false/omitted, create shortcuts apply only while `editingId` is null (Parties create card).
   */
  inlineCreateActive?: boolean;
  canSubmitCreate: boolean;
  canSubmitEdit: boolean;
  createSubmitting: boolean;
  editSubmitting: boolean;
  requestCreateSubmit: () => void;
  requestEditSubmit: () => void;
  requestEditDiscard: () => void;
  /** Invoked for Ctrl/Cmd+Shift+D while focused in the create form when `inlineCreateActive` is true. */
  requestCreateDiscard?: () => void;
}

/**
 * Save: Ctrl/Cmd+S when focus is inside the owning form (inline create, edit, or create card when not editing).
 * Discard: Ctrl/Cmd+Shift+D — edit discard while editing; optional create discard while inline create is active.
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

      const createEl = o.createFormRef.current;
      const editEl = o.editFormRef.current;
      const inCreate = isTargetAssociatedWithForm(target, createEl);
      const inEdit = isTargetAssociatedWithForm(target, editEl);
      const inlineCreate = o.inlineCreateActive === true;

      const saveChord =
        (e.key === "s" || e.key === "S") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;

      const discardChord =
        (e.key === "d" || e.key === "D") && (e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey;

      if (saveChord) {
        if (inlineCreate && inCreate && !o.createSubmitting && o.canSubmitCreate) {
          e.preventDefault();
          o.requestCreateSubmit();
        } else if (o.editingId != null && inEdit && !o.editSubmitting && o.canSubmitEdit) {
          e.preventDefault();
          o.requestEditSubmit();
        } else if (!inlineCreate && o.editingId == null && inCreate && !o.createSubmitting && o.canSubmitCreate) {
          e.preventDefault();
          o.requestCreateSubmit();
        }
        return;
      }

      if (discardChord) {
        if (inlineCreate && inCreate && !o.createSubmitting) {
          e.preventDefault();
          o.requestCreateDiscard?.();
        } else if (o.editingId != null && inEdit && !o.editSubmitting) {
          e.preventDefault();
          o.requestEditDiscard();
        }
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}
