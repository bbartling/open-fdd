/** Recent-N preview from loaded chart series (no historian refetch). */

export const SERIES_PREVIEW_ROW_OPTIONS = [10, 20, 50, 100, 500];
export const DEFAULT_SERIES_PREVIEW_ROWS = 10;

export function coerceSeriesPreviewLimit(value) {
  for (const option of SERIES_PREVIEW_ROW_OPTIONS) {
    if (option === value) return option;
  }
  return DEFAULT_SERIES_PREVIEW_ROWS;
}

function timestampMillis(raw) {
  if (raw == null) return null;
  const ms = Date.parse(String(raw));
  return Number.isFinite(ms) ? ms : null;
}

/**
 * @param {{ name: string, data: Array<[string, number|null]> }[]} lineSeries
 */
export function recentSeriesPreviewFromLines(lineSeries, limit) {
  const n = coerceSeriesPreviewLimit(limit);
  if (!lineSeries?.length) return null;
  const byMs = new Map();
  for (const s of lineSeries) {
    for (const [x] of s.data || []) {
      const ms = timestampMillis(x);
      if (ms != null) byMs.set(ms, String(x));
    }
  }
  if (!byMs.size) return null;
  const newest = [...byMs.entries()].sort((a, b) => a[0] - b[0]).slice(-n).reverse();
  const wanted = new Set(newest.map(([ms]) => ms));
  const used = new Set(["timestamp"]);
  const columns = ["timestamp"];
  const maps = [];
  for (const s of lineSeries) {
    let name = (s.name || "series").trim() || "series";
    while (used.has(name)) name = `${name} (2)`;
    used.add(name);
    columns.push(name);
    const m = new Map();
    for (const [x, y] of s.data || []) {
      const ms = timestampMillis(x);
      if (ms == null || !wanted.has(ms)) continue;
      m.set(ms, y == null ? "" : String(y));
    }
    maps.push(m);
  }
  const rows = newest.map(([ms, label]) => {
    const row = { timestamp: label };
    for (let i = 0; i < maps.length; i++) {
      row[columns[i + 1]] = maps[i].get(ms) ?? "";
    }
    return row;
  });
  return { columns, rows };
}

export function renderPreviewTable(container, table) {
  if (!container) return;
  if (!table?.rows?.length) {
    container.innerHTML = `<p class="hint">No time-series preview for this chart.</p>`;
    return;
  }
  const head = table.columns.map((c) => `<th>${c}</th>`).join("");
  const body = table.rows
    .map((r) => `<tr>${table.columns.map((c) => `<td>${r[c] ?? ""}</td>`).join("")}</tr>`)
    .join("");
  container.innerHTML = `<div class="tablewrap"><table class="bac"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
