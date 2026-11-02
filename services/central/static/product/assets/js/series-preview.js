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

function uniqueColumnName(base, used) {
  const trimmed = (base || "series").trim() || "series";
  if (!used.has(trimmed)) {
    used.add(trimmed);
    return trimmed;
  }
  let i = 2;
  while (used.has(`${trimmed} (${i})`)) i += 1;
  const name = `${trimmed} (${i})`;
  used.add(name);
  return name;
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
    const name = uniqueColumnName(s.name, used);
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
  container.replaceChildren();
  if (!table?.rows?.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No time-series preview for this chart.";
    container.appendChild(p);
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "tablewrap";
  const el = document.createElement("table");
  el.className = "bac";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const c of table.columns) {
    const th = document.createElement("th");
    th.textContent = c;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  el.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const r of table.rows) {
    const tr = document.createElement("tr");
    for (const c of table.columns) {
      const td = document.createElement("td");
      td.textContent = r[c] ?? "";
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  el.appendChild(tbody);
  wrap.appendChild(el);
  container.appendChild(wrap);
}
