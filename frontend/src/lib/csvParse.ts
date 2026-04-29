/** Minimal RFC 4180-style CSV parser for browser-side preview (one UTF-16 code unit at a time). */
export function parseCsv(text: string): string[][] {
  if (!text) {
    return [];
  }

  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let i = 0;
  let inQuotes = false;

  const flushField = () => {
    row.push(field);
    field = "";
  };

  const flushRow = () => {
    flushField();
    rows.push(row);
    row = [];
  };

  while (i < text.length) {
    const c = text[i]!;

    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += c;
      i += 1;
      continue;
    }

    if (c === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }

    if (c === ",") {
      flushField();
      i += 1;
      continue;
    }

    if (c === "\n") {
      flushRow();
      i += 1;
      continue;
    }

    if (c === "\r") {
      i += 1;
      continue;
    }

    field += c;
    i += 1;
  }

  flushField();
  rows.push(row);

  while (rows.length > 0 && rows[rows.length - 1]!.every((cell) => cell === "")) {
    rows.pop();
  }

  if (rows.length === 0) {
    return [];
  }

  return rectangularize(rows);
}

function rectangularize(rows: string[][]): string[][] {
  const maxCols = rows.reduce((max, r) => Math.max(max, r.length), 0);
  return rows.map((r) => {
    const next = [...r];
    while (next.length < maxCols) {
      next.push("");
    }
    return next;
  });
}
