/** Escape one CSV cell; neutralize spreadsheet formula injection. */
export function escapeCsvCell(v: unknown): string {
  let s = v == null ? "" : String(v);
  if (/^[=+\-@]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Client-side CSV download helper for Overview table exports. */
export function downloadRowsCsv(
  filename: string,
  rows: Array<Record<string, unknown>>,
): void {
  if (!rows.length) return;
  const keys = Object.keys(rows[0] ?? {});
  const lines = [
    keys.map((k) => escapeCsvCell(k)).join(","),
    ...rows.map((r) => keys.map((k) => escapeCsvCell(r[k])).join(",")),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
