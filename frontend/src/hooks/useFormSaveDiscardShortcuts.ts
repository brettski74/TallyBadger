import { type RefObject, useEffect, useRef } from "react";

/**
 * True when `target` belongs to this form for keyboard shortcut purposes.
 *
 * `HTMLFormElement.contains()` is false for nodes inside **open shadow roots** even when the
 * shadow host sits in the form (e.g. Chromium date inputs), so we walk `composedPath` / shadow
 * hosts and still honour the `form=""` association on controls outside the subtree.
 */
export function isTargetAssociatedWithForm(
  target: Node,
  form: HTMLFormElement | null,
  event?: Event,
): boolean {
  if (!form) {
    return false;
  }

  if (event && typeof event.composedPath === "function") {
    for (const n of event.composedPath()) {
      if (n === form) {
        return true;
      }
    }
  }

  let node: Node | null = target;
  while (node) {
    if (node === form) {
      return true;
    }
    const root = node.getRootNode();
    if (root instanceof ShadowRoot) {
      node = root.host;
    } else {
      node = node.parentNode;
    }
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
  /**
   * When true and not editing, apply create save/discard chords even when focus is outside the
   * create form (e.g. a modal `<dialog>` after a focused control unmounts on view change).
   */
  createDialogActive?: boolean;
}

/**
 * Save: Ctrl/Cmd+S when focus is inside the owning form (inline create, edit, or create card when not editing).
 * Discard: Ctrl/Cmd+Shift+D — edit discard while editing; optional create discard while inline create is active;
 * optional `requestCreateDiscard` while focus is in `createFormRef` and `editingId` is null (single-form create flows such as CEL rule sets);
 * or optional `createDialogActive` for modal create dialogs (Cheques) when focus is not inside the form.
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
      const inCreate = isTargetAssociatedWithForm(target, createEl, e);
      const inEdit = isTargetAssociatedWithForm(target, editEl, e);
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
        } else if (
          !inlineCreate &&
          o.editingId == null &&
          o.createDialogActive &&
          !o.createSubmitting &&
          o.canSubmitCreate
        ) {
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
        } else if (
          !inlineCreate &&
          o.editingId == null &&
          inCreate &&
          !o.createSubmitting &&
          o.requestCreateDiscard
        ) {
          e.preventDefault();
          o.requestCreateDiscard();
        } else if (
          !inlineCreate &&
          o.editingId == null &&
          o.createDialogActive &&
          !o.createSubmitting &&
          o.requestCreateDiscard
        ) {
          e.preventDefault();
          o.requestCreateDiscard();
        }
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}
