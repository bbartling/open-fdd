// CSV export for the Open-FDD app (Export tab): pick points, a date-time range and a resolution,
// download one Excel-friendly CSV. History comes from NF resampled on the box
// (/api/v1/point/data?...&window=Ns&method=AVERAGE|MAX), in chunks of 7 days or less.
//
// Pure functions (CSV building, range chunking, column naming, unit conversion) are at the top and
// run in node too (tests/export.test.mjs); the DOM wiring is at the bottom. Classic script: the
// browser global is `ofddExport`; needs units.js (ofddUnits), and nf.js / model.js for the DOM part.
(function (root) {
  const units = () => root.ofddUnits || (typeof require !== "undefined" ? require("./units.js") : null);

  const DAY_MS = 24 * 3600e3;
  const MAX_CHUNK_DAYS = 7;
  const MAX_CELLS = 200000;
  const BATCH = 40;                      // uuids per request (keeps the URL short)
  const BOM = "﻿";                  // so Excel reads UTF-8 (°F, ₂) instead of the ANSI code page

  /** Resolution choices: NF window in seconds. "raw" is the box's 5-minute trend grid. */
  const RESOLUTIONS = [
    { id: "raw", label: "Raw (300 s average)", windowSec: 300 },
    { id: "5m", label: "5 min", windowSec: 300 },
    { id: "15m", label: "15 min", windowSec: 900 },
    { id: "1h", label: "1 hour", windowSec: 3600 },
    { id: "1d", label: "1 day (UTC days)", windowSec: 86400 },
  ];
  const windowFor = (id) => (RESOLUTIONS.find((r) => r.id === id) || RESOLUTIONS[0]).windowSec;

  // ---- CSV text ------------------------------------------------------------------------
  // CSV/formula injection: a text cell Excel/Sheets would read as a formula (starts with = + - @,
  // also after leading whitespace, or with TAB/CR) gets a leading ' so it opens as plain text.
  // Real numbers are written as numbers; a text cell that is only a plain number (-3.2) is left alone.
  const FORMULA_START = /^\s*[=+\-@]|^[\t\r]/;
  const PLAIN_NUMBER = /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/;
  /** One CSV field: numbers as-is (empty for null/NaN), text neutralised against formulas, quoted when it holds , " or a line break. */
  function csvCell(v) {
    if (v == null) return "";
    if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
    let s = String(v);
    if (FORMULA_START.test(s) && !PLAIN_NUMBER.test(s)) s = "'" + s;
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
  const csvLine = (cells) => cells.map(csvCell).join(",");

  /** Whole file: UTF-8 BOM + header + rows, CRLF line ends (what Excel writes). */
  function buildCsv(header, rows) {
    return BOM + [csvLine(header), ...rows.map(csvLine)].join("\r\n") + "\r\n";
  }

  // ---- time -----------------------------------------------------------------------------
  const p2 = (n) => String(n).padStart(2, "0");
  /** Local wall-clock ISO without zone: 2026-11-05T13:05:00 */
  function localIso(ms) {
    const d = new Date(ms);
    return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
  }
  const utcIso = (ms) => new Date(ms).toISOString();
  /** <input type=datetime-local> value (minute precision, local). */
  const inputValue = (ms) => localIso(ms).slice(0, 16);
  /** Parse an NF timestamp (nanosecond fractions allowed). */
  const parseNfTs = (ts) => Date.parse(String(ts).replace(/(\.\d{3})\d+/, "$1"));

  /** Split [startMs, endMs) into consecutive pieces of at most maxDays. */
  function chunkRange(startMs, endMs, maxDays = MAX_CHUNK_DAYS) {
    const out = [];
    const step = maxDays * DAY_MS;
    for (let t = startMs; t < endMs; t += step) out.push({ from: t, to: Math.min(t + step, endMs) });
    return out;
  }

  // ---- columns --------------------------------------------------------------------------
  /** "<equip> <point dis> [<unit>]" (equip and unit parts dropped when empty). */
  function columnName(equip, dis, unit) {
    return [equip, dis].filter(Boolean).join(" ") + (unit ? ` [${unit}]` : "");
  }

  /** Make repeated headers unique ("x", "x (2)", …) so Excel columns stay distinguishable. */
  function uniqueHeaders(names) {
    const seen = new Map();
    return names.map((n) => {
      const k = (seen.get(n) || 0) + 1;
      seen.set(n, k);
      return k === 1 ? n : `${n} (${k})`;
    });
  }

  /** Stored unit → { unit label, convert(value) } for "display" (imperial|si) or "stored" mode. */
  function unitFor(unit, mode, system) {
    const u = units();
    if (mode !== "display" || !u) return { unit: unit || "", convert: (v) => v };
    const label = u.display(0, unit, system).unit;
    // toPrecision hides float noise from the F<->C maths (71.60000000000001).
    return { unit: label, convert: (v) => (v == null ? v : Number(u.display(v, unit, system).value.toPrecision(10))) };
  }

  /** Resampling method for a point: MAX for result/bool points (fault flags), else AVERAGE. */
  const methodFor = (p) => (p.kind === "Bool" || (p.tags || []).includes("fault") || (p.tags || []).includes("fdd") ? "MAX" : "AVERAGE");

  /** Rows x columns the export would produce (for the size cap). */
  function estimateCells(nPoints, startMs, endMs, windowSec) {
    const rows = Math.max(0, Math.ceil((endMs - startMs) / (windowSec * 1e3)));
    return { rows, cells: rows * nPoints };
  }

  /** Date-stamped file name: open-fdd_<site>_<start>_<end>.csv (local times). */
  function fileName(site, startMs, endMs) {
    const stamp = (ms) => localIso(ms).slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
    const s = String(site || "site").replace(/[^\w.-]+/g, "_").slice(0, 60);
    return `open-fdd_${s}_${stamp(startMs)}_${stamp(endMs)}.csv`;
  }

  /** /api/v1/point/data URL for one chunk and one method. */
  function dataUrl({ uuids, fromMs, toMs, windowSec, method }) {
    const ids = uuids.map((u) => "uuids=" + encodeURIComponent(u)).join("&");
    return `/api/v1/point/data?${ids}&from=${utcIso(fromMs)}&to=${utcIso(toMs)}&window=${windowSec}s&method=${method}`;
  }

  const sampleValue = (s) => {
    const v = s.double ?? s.real ?? (typeof s.boolean === "boolean" ? +s.boolean : s.enumerated ?? s.unsigned ?? s.signed);
    return v == null ? null : Number(v);
  };

  /**
   * Fetch every point's resampled history. Returns Map(uuid -> Map(ms -> raw value)).
   * Chunks of <= 7 days, points grouped by method and batched; `apiFn(url)` -> NF JSON.
   */
  /** @param {{points: any[], startMs: number, endMs: number, windowSec: number, apiFn: (url: string) => Promise<any>, onProgress?: (done: number, total: number) => void, isCancelled?: () => boolean}} o */
  async function collect({ points, startMs, endMs, windowSec, apiFn, onProgress = () => {}, isCancelled = () => false }) {
    const out = new Map(points.map((p) => [p.uuid, new Map()]));
    const groups = new Map();
    for (const p of points) {
      const m = methodFor(p);
      if (!groups.has(m)) groups.set(m, []);
      groups.get(m).push(p);
    }
    const jobs = [];
    for (const ch of chunkRange(startMs, endMs)) {
      for (const [method, list] of groups) {
        for (let i = 0; i < list.length; i += BATCH) jobs.push({ ch, method, list: list.slice(i, i + BATCH) });
      }
    }
    let done = 0;
    for (const job of jobs) {
      if (isCancelled()) throw new Error("cancelled");
      onProgress(done, jobs.length);
      const res = await apiFn(dataUrl({ uuids: job.list.map((p) => p.uuid), fromMs: job.ch.from, toMs: job.ch.to, windowSec, method: job.method }));
      for (const series of res.data || []) {
        const m = out.get(series.uuid);
        if (!m) continue;
        for (const s of series.values || []) {
          const v = sampleValue(s);
          const t = s.ts ? parseNfTs(s.ts) : NaN;
          if (v != null && Number.isFinite(t)) m.set(t, v);
        }
      }
      done++;
    }
    onProgress(done, jobs.length);
    return out;
  }

  /**
   * CSV from collected data. columns = [{ uuid, equip, dis, unit }] (stored unit);
   * mode "display" converts to `system`, "stored" keeps NF's unit. Rows are the union of
   * timestamps; a point with no sample at a timestamp leaves the cell empty.
   */
  function toCsv({ columns, data, mode = "display", system = "imperial", startMs = -Infinity, endMs = Infinity }) {
    const conv = columns.map((c) => unitFor(c.unit, mode, system));
    const header = ["timestamp", "timestamp_utc",
      ...uniqueHeaders(columns.map((c, i) => columnName(c.equip, c.dis, conv[i].unit)))];
    const times = [...new Set(columns.flatMap((c) => [...(data.get(c.uuid) || new Map()).keys()]))]
      .filter((t) => t >= startMs && t < endMs).sort((a, b) => a - b);
    const rows = times.map((t) => [localIso(t), utcIso(t),
      ...columns.map((c, i) => { const v = (data.get(c.uuid) || new Map()).get(t); return v == null ? null : conv[i].convert(v); })]);
    return { csv: buildCsv(header, rows), rows: rows.length };
  }

  /** Check the request; returns an error string or "". */
  function validate({ nPoints, startMs, endMs, windowSec }) {
    if (!nPoints) return "Select at least one point.";
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return "Pick a start and an end date-time.";
    if (endMs <= startMs) return "The end must be after the start.";
    const { rows, cells } = estimateCells(nPoints, startMs, endMs, windowSec);
    if (cells > MAX_CELLS) {
      return `That is about ${cells.toLocaleString()} cells (${nPoints} points x ${rows.toLocaleString()} rows); the limit is ${MAX_CELLS.toLocaleString()}. `
        + "Shorten the range, pick a coarser resolution or select fewer points.";
    }
    return "";
  }

  const pure = {
    BOM, MAX_CELLS, MAX_CHUNK_DAYS, RESOLUTIONS, windowFor, csvCell, csvLine, buildCsv, localIso, utcIso, inputValue,
    parseNfTs, chunkRange, columnName, uniqueHeaders, unitFor, methodFor, estimateCells, fileName, dataUrl, collect, toCsv, validate,
  };

  // ---- DOM (browser only) ----------------------------------------------------------------
    /** @param {string} id @returns {AnyEl} */
  const $ = (id) => /** @type {AnyEl} */ (root.document.getElementById(id));
  const st = { key: "", selected: new Set(), mounted: false, busy: false, cur: null };

  const equipName = (model, p) => {
    if (p.equipRef) {
      const e = model.equips.find((x) => (((x.attrs || {}).id) || x.name) === p.equipRef);
      return (e && ((e.attrs || {}).dis || e.name)) || p.equipRef;
    }
    return p.weatherStationRef || "";
  };

  /** Points in the current site/equip scope that have history (tagged, trended, not spare). */
  function candidates(model, scope) {
    const tagged = (p) => p.tags.includes("point") && p.tags.includes("his") && !p.tags.includes("spare");
    return model.points
      .filter((p) => p.siteRef === scope.site && tagged(p) && (p.kind === "Number" || p.kind === "Bool"))
      .filter((p) => !scope.equip || p.equipRef === scope.equip || p.weatherStationRef)
      .map((p) => ({ p, equip: equipName(model, p) }))
      .sort((a, b) => a.equip.localeCompare(b.equip) || a.p.dis.localeCompare(b.p.dis));
  }

  const system = () => (units() ? units().displaySystem() : "imperial");
  const mode = () => $("exUnits").value;
  const unitText = (p) => unitFor(p.units, mode(), system()).unit;
  const labelOf = ({ p, equip }) => columnName(equip, p.dis, unitText(p));

  function visibleRows() {
    const tokens = $("exFilter").value.toLowerCase().split(/[\s,]+/).filter(Boolean);
    return st.rows.filter((r) => {
      const hay = (labelOf(r) + " " + r.p.tags.join(" ")).toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
  }

  function drawList() {
    const rows = visibleRows();
    $("exList").innerHTML = rows.map((r) => `<label class="ex-row"><input type="checkbox" data-uuid="${esc(r.p.uuid)}"${st.selected.has(r.p.uuid) ? " checked" : ""}>`
      + `<span>${esc(labelOf(r))}</span></label>`).join("") || `<div class="sub">No points match.</div>`;
    $("exShown").textContent = `${rows.length} of ${st.rows.length} shown`;
    refreshSummary();
  }

  function readRange() {
    return { startMs: new Date($("exStart").value).getTime(), endMs: new Date($("exEnd").value).getTime() };
  }

  function refreshSummary() {
    const { startMs, endMs } = readRange();
    const windowSec = windowFor($("exRes").value);
    const n = st.selected.size;
    const err = validate({ nPoints: n, startMs, endMs, windowSec });
    const { rows, cells } = Number.isFinite(startMs + endMs) && endMs > startMs ? estimateCells(n, startMs, endMs, windowSec) : { rows: 0, cells: 0 };
    const reqs = Number.isFinite(startMs + endMs) && endMs > startMs ? chunkRange(startMs, endMs).length : 0;
    $("exSummary").textContent = err || `${n} point${n === 1 ? "" : "s"} x about ${rows.toLocaleString()} rows = ${cells.toLocaleString()} cells · ${reqs} time chunk${reqs === 1 ? "" : "s"} of at most ${MAX_CHUNK_DAYS} days`;
    $("exSummary").classList.toggle("warn", !!err && n > 0);
    $("exGo").disabled = st.busy || !!err;
  }

  function download(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    const a = Object.assign(root.document.createElement("a"), { href: url, download: name });
    root.document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  async function run() {
    const { model, scope } = st.cur;
    const { startMs, endMs } = readRange();
    const windowSec = windowFor($("exRes").value);
    const sel = st.rows.filter((r) => st.selected.has(r.p.uuid));
    const err = validate({ nPoints: sel.length, startMs, endMs, windowSec });
    if (err) { $("exStatus").textContent = err; return; }
    st.busy = true;
    $("exGo").disabled = true;
    try {
      // Align the start to the window so every chunk shares NF's window grid.
      const from = Math.floor(startMs / (windowSec * 1e3)) * windowSec * 1e3;
      const data = await collect({
        points: sel.map((r) => r.p), startMs: from, endMs, windowSec, apiFn: (u) => api(u),
        onProgress: (i, n) => { $("exStatus").textContent = `loading ${Math.min(i + 1, n)} of ${n} request${n === 1 ? "" : "s"}…`; },
      });
      const { csv, rows } = toCsv({
        columns: sel.map((r) => ({ uuid: r.p.uuid, equip: r.equip, dis: r.p.dis, unit: r.p.units })),
        data, mode: mode(), system: system(), startMs: from, endMs,
      });
      const site = (model.sites.find((s) => (((s.attrs || {}).id) || s.name) === scope.site) || {}).name || scope.site;
      const name = fileName(site, startMs, endMs);
      if (!rows) { $("exStatus").textContent = "NF returned no samples for that range."; return; }
      download(name, csv);
      $("exStatus").textContent = `saved ${name} · ${rows.toLocaleString()} rows x ${sel.length} points`;
    } catch (e) {
      $("exStatus").textContent = `export failed: ${e.message}`;
    } finally {
      st.busy = false;
      refreshSummary();
    }
  }

  function mount() {
    st.mounted = true;
    $("exRes").innerHTML = RESOLUTIONS.map((r) => `<option value="${r.id}">${r.label}</option>`).join("");
    $("exRes").value = "15m";
    const now = Date.now();
    $("exStart").value = inputValue(now - DAY_MS);
    $("exEnd").value = inputValue(now);
    for (const id of ["exStart", "exEnd", "exRes"]) $(id).addEventListener("input", refreshSummary);
    $("exUnits").addEventListener("input", drawList);
    $("exFilter").addEventListener("input", drawList);
    $("exAll").addEventListener("click", () => { for (const r of visibleRows()) st.selected.add(r.p.uuid); drawList(); });
    $("exNone").addEventListener("click", () => { for (const r of visibleRows()) st.selected.delete(r.p.uuid); drawList(); });
    $("exList").addEventListener("change", (ev) => {
      const t = /** @type {HTMLInputElement} */ (ev.target);
      const id = t.dataset && t.dataset.uuid;
      if (!id) return;
      if (t.checked) st.selected.add(id); else st.selected.delete(id);
      refreshSummary();
    });
    $("exGo").addEventListener("click", () => run());
  }

  /** Draw/refresh the Export tab for the current scope ({ model, scope }). */
  function render(ctx) {
    st.cur = ctx;
    if (!st.mounted) mount();
    const key = `${ctx.scope.site}|${ctx.scope.equip}`;
    st.rows = candidates(ctx.model, ctx.scope);
    if (key !== st.key) {                        // new scope: start with every point in it selected
      st.key = key;
      st.selected = new Set(st.rows.map((r) => r.p.uuid));
    } else {
      const have = new Set(st.rows.map((r) => r.p.uuid));
      for (const id of [...st.selected]) if (!have.has(id)) st.selected.delete(id);
    }
    const sys = system();
    $("exUnits").options[0].textContent = `As displayed (${sys === "si" ? "SI" : "imperial"})`;
    drawList();
  }

  const exported = { ...pure, render };   // not named `api`: the DOM code calls nf.js api()
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  root.ofddExport = exported;
})(typeof globalThis !== "undefined" ? globalThis : this);
