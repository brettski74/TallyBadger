export function saveActionTooltip(isMac: boolean): string {
  return isMac ? "Save (⌘+S)" : "Save (Ctrl+S)";
}

export function discardActionTooltip(isMac: boolean): string {
  return isMac ? "Discard (⌘+Shift+D)" : "Discard (Ctrl+Shift+D)";
}

export function saveAriaKeyShortcuts(isMac: boolean): string {
  return isMac ? "Meta+S" : "Control+S";
}

export function discardAriaKeyShortcuts(isMac: boolean): string {
  return isMac ? "Meta+Shift+D" : "Control+Shift+D";
}

export function previewEditActionTooltip(isMac: boolean): string {
  return isMac ? "Edit (⌘+Shift+D)" : "Edit (Ctrl+Shift+D)";
}

export function previewEditAriaKeyShortcuts(isMac: boolean): string {
  return isMac ? "Meta+Shift+D" : "Control+Shift+D";
}
