/** Ctrl/Cmd+N — new entity on list views. Uses `code` so Linux/Firefox control-character `key` values still match. */
export function isNewChord(e: KeyboardEvent): boolean {
  const keyMatch = e.key === "n" || e.key === "N";
  const codeMatch = e.code === "KeyN";
  return (keyMatch || codeMatch) && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
}
