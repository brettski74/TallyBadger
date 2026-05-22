export function saveActionTooltip(isMac: boolean): string {
  return isMac ? "Save (⌘+S)" : "Save (Ctrl+S)";
}

export function revertActionTooltip(isMac: boolean): string {
  return isMac ? "Revert (⌘+Shift+D)" : "Revert (Ctrl+Shift+D)";
}

export function newActionTooltip(isMac: boolean): string {
  return isMac ? "New (⌘+N)" : "New (Ctrl+N)";
}

export function closeActionTooltip(isMac: boolean): string {
  return isMac ? "Close (Esc)" : "Close (Esc)";
}

export function saveAriaKeyShortcuts(isMac: boolean): string {
  return isMac ? "Meta+S" : "Control+S";
}

export function revertAriaKeyShortcuts(isMac: boolean): string {
  return isMac ? "Meta+Shift+D" : "Control+Shift+D";
}

export function newAriaKeyShortcuts(isMac: boolean): string {
  return isMac ? "Meta+N" : "Control+N";
}

/** Preview step: return to the editable form without changing saved field values. */
export function previewReturnToFormActionTooltip(isMac: boolean): string {
  return isMac ? "Return to form (⌘+Shift+D)" : "Return to form (Ctrl+Shift+D)";
}

export function previewReturnToFormAriaKeyShortcuts(isMac: boolean): string {
  return isMac ? "Meta+Shift+D" : "Control+Shift+D";
}
