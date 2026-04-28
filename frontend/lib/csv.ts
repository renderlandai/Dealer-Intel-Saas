/**
 * Minimal RFC 4180-style CSV parser. Handles:
 *   - quoted fields with commas, newlines, and escaped quotes ("")
 *   - CRLF and LF line endings
 *   - trailing empty line
 *
 * Returns rows as string[][] with no header interpretation.
 */
export function parseCsv(input: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  let i = 0;
  const len = input.length;

  while (i < len) {
    const ch = input[i];

    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < len && input[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += ch;
      i += 1;
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (ch === ",") {
      row.push(field);
      field = "";
      i += 1;
      continue;
    }
    if (ch === "\r") {
      // swallow \r; \n on the next iteration ends the row
      i += 1;
      continue;
    }
    if (ch === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      i += 1;
      continue;
    }
    field += ch;
    i += 1;
  }

  // flush last field/row if file didn't end with a newline
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  // drop completely-empty trailing rows (e.g. file ending in \n then EOF)
  while (rows.length > 0 && rows[rows.length - 1].every((c) => c === "")) {
    rows.pop();
  }

  return rows;
}

/**
 * Parse a CSV string into an array of row objects, keyed by normalized headers.
 * Header normalization: lowercase, trim, replace whitespace/dashes with `_`.
 */
export function parseCsvWithHeaders(input: string): {
  headers: string[];
  rows: Record<string, string>[];
} {
  const matrix = parseCsv(input);
  if (matrix.length === 0) return { headers: [], rows: [] };

  const headers = matrix[0].map(normalizeHeader);
  const rows = matrix.slice(1).map((cols) => {
    const obj: Record<string, string> = {};
    headers.forEach((h, idx) => {
      obj[h] = (cols[idx] ?? "").trim();
    });
    return obj;
  });
  return { headers, rows };
}

function normalizeHeader(raw: string): string {
  return raw.trim().toLowerCase().replace(/[\s-]+/g, "_");
}
