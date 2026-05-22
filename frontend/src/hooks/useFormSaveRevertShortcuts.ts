import { type RefObject, useEffect, useRef } from "react";

import { isNewChord } from "../lib/keyboardChords";

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

function isSaveChord(e: KeyboardEvent): boolean {
  return (e.key === "s" || e.key === "S") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
}

function isRevertChord(e: KeyboardEvent): boolean {
  return (e.key === "d" || e.key === "D") && (e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey;
}

export interface FormSaveRevertShortcutOptions {
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
  /** Ctrl/Cmd+Shift+D while editing: revert draft to last saved values in place. */
  requestEditRevert: () => void;
  /** Ctrl/Cmd+Shift+D on inline create or single-form create (e.g. CEL). */
  requestCreateRevert?: () => void;
  /**
   * When true and not editing, apply create save/revert chords even when focus is outside the
   * create form (e.g. a modal `<dialog>` after a focused control unmounts on view change).
   */
  createDialogActive?: boolean;
  /** Esc: abandon inline create without saving. */
  requestCreateClose?: () => void;
  /** Esc: close inline edit without saving. */
  requestEditClose?: () => void;
  /** When true, Esc invokes create/edit close handlers when the matching editor is active. */
  escapeActive?: boolean;
  /** Ctrl/Cmd+Shift+N: open create flow for the current view. */
  requestNew?: () => void;
  /** When false, Ctrl/Cmd+Shift+N is ignored (e.g. modal already open). */
  newShortcutActive?: boolean;
}

/**
 * Save: Ctrl/Cmd+S when focus is inside the owning form (or create dialog is active).
 * Revert: Ctrl/Cmd+Shift+D — restore draft to last saved values in place.
 * Close: Esc — abandon editor without saving (when `escapeActive` and close handlers are set).
 * New: Ctrl/Cmd+Shift+N when `newShortcutActive` (default true if `requestNew` is set).
 */
export function useFormSaveRevertShortcuts(opts: FormSaveRevertShortcutOptions): void {
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const o = optsRef.current;
      const target = e.target;
      if (!(target instanceof Node)) {
        return;
      }

      if (e.key === "Escape" && o.escapeActive) {
        if (o.inlineCreateActive && o.requestCreateClose) {
          e.preventDefault();
          o.requestCreateClose();
          return;
        }
        if (o.editingId != null && o.requestEditClose) {
          e.preventDefault();
          o.requestEditClose();
          return;
        }
        if (o.createDialogActive && o.requestCreateClose) {
          e.preventDefault();
          o.requestCreateClose();
          return;
        }
      }

      if (isNewChord(e) && o.requestNew && o.newShortcutActive !== false) {
        e.preventDefault();
        o.requestNew();
        return;
      }

      const createEl = o.createFormRef.current;
      const editEl = o.editFormRef.current;
      const inCreate = isTargetAssociatedWithForm(target, createEl, e);
      const inEdit = isTargetAssociatedWithForm(target, editEl, e);
      const inlineCreate = o.inlineCreateActive === true;

      if (isSaveChord(e)) {
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

      if (isRevertChord(e)) {
        if (inlineCreate && inCreate && !o.createSubmitting) {
          e.preventDefault();
          o.requestCreateRevert?.();
        } else if (o.editingId != null && inEdit && !o.editSubmitting) {
          e.preventDefault();
          o.requestEditRevert();
        } else if (
          !inlineCreate &&
          o.editingId == null &&
          inCreate &&
          !o.createSubmitting &&
          o.requestCreateRevert
        ) {
          e.preventDefault();
          o.requestCreateRevert();
        } else if (
          !inlineCreate &&
          o.editingId == null &&
          o.createDialogActive &&
          !o.createSubmitting &&
          o.requestCreateRevert
        ) {
          e.preventDefault();
          o.requestCreateRevert();
        }
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, []);
}
