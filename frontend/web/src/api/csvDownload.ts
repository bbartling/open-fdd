/** Client-side CSV download helper for Overview table exports. */
export function downloadRowsCsv(
  filename: string,
  rows: Array<Record<string, unknown>>,
): void {
  if (!rows.length) return;
  const keys = Object.keys(rows[0] ?? {});
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [
    keys.join(","),
    ...rows.map((r) => keys.map((k) => esc(r[k])).join(",")),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
