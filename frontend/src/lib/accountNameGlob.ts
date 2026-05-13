/**
 * Case-insensitive glob match for account names: only `*` and `?` are wildcards;
 * other characters are matched literally (regex metacharacters are escaped).
 */
export function accountNameMatchesGlob(accountName: string, pattern: string): boolean {
  const p = pattern.trim();
  if (p === "") {
    return true;
  }
  let source = "";
  for (const ch of p) {
    if (ch === "*") {
      source += ".*";
    } else if (ch === "?") {
      source += ".";
    } else if (/[.+^${}()|[\]\\]/.test(ch)) {
      source += `\\${ch}`;
    } else {
      source += ch;
    }
  }
  const re = new RegExp(`^${source}$`, "i");
  return re.test(accountName);
}
