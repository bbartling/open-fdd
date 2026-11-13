// CSV export for the Open-FDD app (Export tab): single-equipment joined I/O + published FDD results,
// stored units and source history types, exact source timestamp join with 10k-sample cap detection,
// aligned bucketed fallback, and Full Timescale long-range fallback.
//
// Pure functions are at the top and run in Node too (tests/export.test.mjs); DOM wiring is at the bottom.
(function (root) {
  const units = () => root.ofddUnits || (typeof require !== "undefined" ? require("./units.js") : null);

  const DAY_MS = 24 * 3600e3;
  const MAX_CHUNK_DAYS = 7;
  const MAX_CELLS = 200000;
  const MAX_BYTES = 20 * 1024 * 1024;
  const NF_SAMPLE_LIMIT = 10000;
  const BATCH = 40;
  const URL_BUDGET = 6000;
  const BOM = "\uFEFF";

  const RESOLUTIONS = [
    { id: "raw", label: "Raw (300 s average)", windowSec: 300 },
    { id: "5m", label: "5 min", windowSec: 300 },
    { id: "15m", label: "15 min", windowSec: 900 },
    { id: "1h", label: "1 hour", windowSec: 3600 },
    { id: "1d", label: "1 day (UTC days)", windowSec: 86400 },
  ];
  const windowFor = (id) => (RESOLUTIONS.find((r) => r.id === id) || RESOLUTIONS[0]).windowSec;

  // ---- CSV text ------------------------------------------------------------------------
  const FORMULA_START = /^\s*[=+\-@]|^[\t\r]/;
  const PLAIN_NUMBER = /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/;

  function csvCell(v) {
    if (v == null) return "";
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
    let s = String(v);
    if (FORMULA_START.test(s) && !PLAIN_NUMBER.test(s)) s = "'" + s;
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
  const csvLine = (cells) => cells.map(csvCell).join(",");

  function buildCsv(header, rows) {
    return BOM + [csvLine(header), ...rows.map(csvLine)].join("\r\n") + "\r\n";
  }

  function utf8ByteLength(str) {
    if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(str).length;
    if (typeof Buffer !== "undefined") return Buffer.byteLength(str, "utf8");
    return str.length * 2;
  }

  // ---- time -----------------------------------------------------------------------------
  const p2 = (n) => String(n).padStart(2, "0");
  function localIso(ms, tz) {
    if (tz && root.ofddSchedule) {
      const p = root.ofddSchedule.localParts(ms, tz);
      return `${p.y}-${p2(p.m)}-${p2(p.d)}T${p2(p.h)}:${p2(p.mi)}:${p2(p.s)}`;
    }
    const d = new Date(ms);
    return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
  }
  const utcIso = (ms) => new Date(ms).toISOString();
  const inputValue = (ms) => localIso(ms).slice(0, 16);
  const parseNfTs = (ts) => Date.parse(String(ts).replace(/(\.\d{3})\d+/, "$1"));

  function chunkRange(startMs, endMs, maxDays = MAX_CHUNK_DAYS) {
    const out = [];
    const step = maxDays * DAY_MS;
    for (let t = startMs; t < endMs; t += step) out.push({ from: t, to: Math.min(t + step, endMs) });
    return out;
  }

  // ---- columns --------------------------------------------------------------------------
  function columnName(equip, dis, unit) {
    return [equip, dis].filter(Boolean).join(" ") + (unit ? ` [${unit}]` : "");
  }

  function uniqueHeaders(names) {
    const seen = new Map();
    return names.map((n) => {
      const k = (seen.get(n) || 0) + 1;
      seen.set(n, k);
      return k === 1 ? n : `${n} (${k})`;
    });
  }

  function unitFor(unit, mode, system) {
    const u = units();
    if (mode !== "display" || !u) return { unit: unit || "", convert: (v) => v };
    const label = u.display(0, unit, system).unit;
    return {
      unit: label,
      convert: (v) => (v == null || typeof v !== "number" ? v : Number(u.display(v, unit, system).value.toPrecision(10))),
    };
  }

  const tagsOf = (p) => {
    if (Array.isArray(p?.tags)) return p.tags;
    const raw = (p?.rec?.attrs || {}).markers;
    if (Array.isArray(raw)) return raw;
    return typeof raw === "string" ? raw.split(",").map((x) => x.trim()).filter(Boolean) : [];
  };
  const attrsOf = (p) => (p?.rec && p.rec.attrs) || {};
  const idOfRec = (r) => (r && (r.attrs?.id || r.name)) || "";
  const isWeatherPt = (p) => tagsOf(p).includes("weather") || !!p.weatherStationRef || !!attrsOf(p).weatherStationRef;
  const isFddPt = (p) => tagsOf(p).includes("fdd") || tagsOf(p).includes("fault") || tagsOf(p).includes("fault_timeline") || !!attrsOf(p).ruleRef;

  /** Resampling method for a point in bucketed fallback: MAX for Bool / fault / fault_timeline / fdd / ruleRef, LAST for String/Enum, else AVERAGE. */
  function methodFor(p) {
    const tags = tagsOf(p);
    const attrs = attrsOf(p);
    if (p.kind === "Bool" || tags.includes("fault_timeline") || tags.includes("fault") || tags.includes("fdd") || !!attrs.ruleRef) {
      return "MAX";
    }
    if (p.kind === "String" || p.kind === "Enum" || tags.includes("enum")) return "LAST";
    return "AVERAGE";
  }

  function estimateCells(nPoints, startMs, endMs, windowSec) {
    const rows = Math.max(0, Math.ceil((endMs - startMs) / (windowSec * 1e3)));
    return { rows, cells: rows * nPoints };
  }

  function fileName(scopeLabel, startMs, endMs, tz) {
    const stamp = (ms) => localIso(ms, tz).slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
    const s = String(scopeLabel || "equip").replace(/[^\w.-]+/g, "_").slice(0, 60);
    return `open-fdd_${s}_${stamp(startMs)}_${stamp(endMs)}.csv`;
  }

  function dataUrl({ uuids, fromMs, toMs, windowSec, method }) {
    const ids = uuids.map((u) => "uuids=" + encodeURIComponent(u)).join("&");
    return `/api/v1/point/data?${ids}&from=${utcIso(fromMs)}&to=${utcIso(toMs)}&window=${windowSec}s&method=${method}&count=${NF_SAMPLE_LIMIT}&reverse=false`;
  }

  function rawDataUrl({ uuids, fromMs, toMs }) {
    const ids = uuids.map((u) => "uuids=" + encodeURIComponent(u)).join("&");
    return `/api/v1/point/data?${ids}&from=${utcIso(fromMs)}&to=${utcIso(toMs)}&count=${NF_SAMPLE_LIMIT}&reverse=false`;
  }

  function sampleValue(s) {
    if (!s || typeof s !== "object") return null;
    if (s.characterString != null) return String(s.characterString);
    if (typeof s.boolean === "boolean") return s.boolean;
    if (s.enumerated != null) return typeof s.enumerated === "string" ? s.enumerated : Number(s.enumerated);
    const v = s.double ?? s.real ?? s.unsigned ?? s.signed;
    return v == null ? null : Number(v);
  }

  function batchPointsForUrl(list, urlBuilder) {
    const batches = [];
    let cur = [];
    for (const p of list) {
      const next = [...cur, p];
      if (cur.length && (next.length > BATCH || urlBuilder(next).length > URL_BUDGET)) {
        batches.push(cur);
        cur = [p];
      } else {
        cur = next;
      }
      if (urlBuilder(cur).length > URL_BUDGET) {
        throw new Error("point history request exceeds the safe URL limit");
      }
    }
    if (cur.length) batches.push(cur);
    return batches;
  }

  /** Build strict single-equipment membership (Overview I/O + published FDD results, never whole-site). */
  function exportCandidates(model, scope, opts = {}) {
    if (!model || !scope || !scope.site || !scope.equip || scope.equip === "__weather__") {
      return { equip: null, equipId: "", equipLabel: "", columns: [], ioPoints: [], fddPoints: [], trended: [], currentOnly: [], gaps: [] };
    }
    const invFn = opts.inventoryFn || root.scopedEquipmentInventory;
    let inv;
    if (typeof invFn === "function") {
      inv = invFn(model, scope.site, scope.equip, opts);
    } else {
      const equip = (model.equips || []).find((e) => idOfRec(e) === scope.equip && (e.attrs || {}).siteRef === scope.site) || null;
      if (!equip) inv = { equip: null, ioPoints: [], fddPoints: [], gaps: [] };
      else {
        const devEquips = new Map();
        for (const d of model.devices || []) {
          if ((d.attrs || {}).siteRef !== scope.site) continue;
          const did = idOfRec(d);
          if (!devEquips.has(did)) devEquips.set(did, new Set());
          if ((d.attrs || {}).equipRef) devEquips.get(did).add((d.attrs || {}).equipRef);
        }
        for (const p of model.points || []) {
          if (p.siteRef === scope.site && p.deviceRef && p.equipRef) {
            if (!devEquips.has(p.deviceRef)) devEquips.set(p.deviceRef, new Set());
            devEquips.get(p.deviceRef).add(p.equipRef);
          }
        }
        const uniqueDevs = new Set([...devEquips.entries()].filter(([, s]) => s.size === 1 && s.has(scope.equip)).map(([d]) => d));
        const ioPoints = [], fddPoints = [], gaps = [];
        for (const p of model.points || []) {
          const tags = tagsOf(p);
          if (!tags.includes("point") || tags.includes("spare") || isWeatherPt(p)) continue;
          const belongs = p.equipRef === scope.equip || (!p.equipRef && p.deviceRef && uniqueDevs.has(p.deviceRef));
          if (!belongs) continue;
          if (p.siteRef !== scope.site) { gaps.push({ point: p, reason: p.siteRef ? `siteRef=${p.siteRef}` : "missing siteRef" }); continue; }
          if (isFddPt(p)) fddPoints.push(p);
          else ioPoints.push({ point: p, uuid: p.uuid, label: p.dis || p.name || p.uuid, historyAvailable: tags.includes("his") });
        }
        inv = { equip, ioPoints, fddPoints, gaps };
      }
    }
    if (!inv || !inv.equip) {
      return { equip: null, equipId: "", equipLabel: "", columns: [], ioPoints: [], fddPoints: [], trended: [], currentOnly: [], gaps: inv?.gaps || [] };
    }
    const equipId = idOfRec(inv.equip);
    const equipLabel = (inv.equip.attrs && inv.equip.attrs.dis) || inv.equip.name || equipId;
    const byUuid = new Map((model.points || []).map((p) => [p.uuid, p]));

    const ioColumns = (inv.ioPoints || []).map((row) => {
      const p = row.point || row;
      const tags = tagsOf(p);
      return {
        uuid: p.uuid,
        point: p,
        equip: equipLabel,
        dis: p.dis || p.name || p.uuid,
        unit: p.units || "",
        kind: p.kind || "Number",
        lane: "io",
        historyAvailable: tags.includes("his"),
        fddOutputSinceMs: null,
      };
    });

    const fddColumns = [...(inv.fddPoints || [])].map((p) => {
      const attrs = attrsOf(p);
      const tags = tagsOf(p);
      const isTimeline = tags.includes("fault_timeline");
      const ruleRef = String(attrs.ruleRef || "").trim();
      const sensorRef = String(attrs.sensorRef || "").trim();
      const sensorPt = sensorRef ? byUuid.get(sensorRef) : null;
      const sensorLabel = sensorPt ? (sensorPt.dis || sensorPt.name || sensorRef) : sensorRef;
      const outputKind = isTimeline ? "fault_timeline" : String(attrs.fddOutput || "").trim();
      const unit = p.units || (isTimeline ? "0/1" : outputKind === "fault_hours" ? "h" : outputKind === "fault_pct" ? "%" : "");
      let dis = p.dis || p.name || p.uuid;
      if (ruleRef) {
        const parts = [ruleRef];
        if (sensorLabel) parts.push(sensorLabel);
        if (isTimeline) parts.push("fault_timeline");
        else if (outputKind === "fault_hours" || outputKind === "fault_pct") parts.push(outputKind);
        else if (!sensorLabel) parts.push("fault");
        dis = parts.join(" · ");
      }
      const boundary = Date.parse(attrs.fddOutputSince || "");
      return {
        uuid: p.uuid,
        point: p,
        equip: equipLabel,
        dis,
        unit,
        kind: p.kind || "Number",
        lane: isTimeline ? "fault_timeline" : "fdd",
        ruleRef,
        sensorRef,
        outputKind,
        historyAvailable: tags.includes("his"),
        fddOutputSinceMs: Number.isFinite(boundary) ? boundary : null,
      };
    }).sort((a, b) =>
      (a.ruleRef || "").localeCompare(b.ruleRef || "")
      || (a.sensorRef ? 1 : 0) - (b.sensorRef ? 1 : 0)
      || (a.lane === "fault_timeline" ? 0 : 1) - (b.lane === "fault_timeline" ? 0 : 1)
      || a.dis.localeCompare(b.dis)
      || String(a.uuid).localeCompare(String(b.uuid)));

    const columns = [...ioColumns, ...fddColumns];
    return {
      equip: inv.equip,
      equipId,
      equipLabel,
      columns,
      ioPoints: ioColumns,
      fddPoints: fddColumns,
      trended: columns.filter((c) => c.historyAvailable),
      currentOnly: columns.filter((c) => !c.historyAvailable),
      gaps: inv.gaps || [],
    };
  }

  async function collect({ points, startMs, endMs, windowSec, apiFn, onProgress = /** @type {(done: number, total: number) => void} */ (() => {}), isCancelled = () => false }) {
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
        for (const batch of batchPointsForUrl(list, (b) => dataUrl({ uuids: b.map((p) => p.uuid), fromMs: ch.from, toMs: ch.to, windowSec, method }))) {
          jobs.push({ ch, method, list: batch });
        }
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

  function bucketLabelForSec(sec) {
    if (sec <= 300) return "5 minutes";
    if (sec <= 900) return "15 minutes";
    if (sec <= 3600) return "1 hour";
    if (sec <= 21600) return "6 hours";
    return "1 day";
  }

  function pickBucketSecForCap(nColumns, startMs, endMs, maxCells) {
    for (const sec of [300, 900, 3600, 14400, 86400]) {
      if (estimateCells(Math.max(1, nColumns), startMs, endMs, sec).cells <= maxCells) return sec;
    }
    return null;
  }

  /**
   * Collect joined history for one equipment's columns:
   * 1) Exact raw NF timestamps via /api/v1/point/data without window/method, subdividing any chunk that hits NF's 10k sample cap.
   * 2) Falls back to aligned buckets if raw density exceeds maxCells or un-splittable 10k limit.
   * 3) Queries Full Timescale `timescaleFn` (hooks/history) when the requested range starts before NF retention.
   */
  async function collectJoined({
    columns,
    startMs,
    endMs,
    apiFn,
    timescaleFn = null,
    maxCells = MAX_CELLS,
    allowFallback = true,
    onProgress = /** @type {(done: number, total: number) => void} */ (() => {}),
    isCancelled = () => false,
  }) {
    const trendedCols = (columns || []).filter((c) => c.historyAvailable);
    const out = new Map((columns || []).map((c) => [c.uuid, new Map()]));
    if (!trendedCols.length) {
      return { data: out, mode: "raw", windowSec: 0, timescaleUsed: false, timescaleSkippedCols: [], truncated: false };
    }

    const rawJobs = [];
    for (const ch of chunkRange(startMs, endMs)) {
      for (const batch of batchPointsForUrl(trendedCols.map((c) => c.point || c), (b) => rawDataUrl({ uuids: b.map((p) => p.uuid), fromMs: ch.from, toMs: ch.to }))) {
        rawJobs.push({ from: ch.from, to: ch.to, list: batch, depth: 0 });
      }
    }

    let rawTooDense = false;
    let done = 0;
    let rawSamples = 0;
    const rawLimitPerQuery = NF_SAMPLE_LIMIT;

    while (rawJobs.length) {
      if (isCancelled()) throw new Error("cancelled");
      const job = rawJobs.shift();
      onProgress(done, done + rawJobs.length + 1);
      const res = await apiFn(rawDataUrl({ uuids: job.list.map((p) => p.uuid), fromMs: job.from, toMs: job.to }));
      const seriesList = res.data || [];
      const hitCap = seriesList.some((s) => (s.values || []).length >= rawLimitPerQuery);
      if (hitCap) {
        if (job.list.length > 1) {
          for (const single of job.list) rawJobs.unshift({ from: job.from, to: job.to, list: [single], depth: job.depth });
          continue;
        }
        if (job.to - job.from > 60e3 && job.depth < 12) {
          const mid = Math.floor((job.from + job.to) / 2);
          if (mid > job.from && mid < job.to) {
            rawJobs.unshift({ from: mid, to: job.to, list: job.list, depth: job.depth + 1 });
            rawJobs.unshift({ from: job.from, to: mid, list: job.list, depth: job.depth + 1 });
            continue;
          }
        }
        rawTooDense = true;
        break;
      }
      for (const series of seriesList) {
        const m = out.get(series.uuid);
        if (!m) continue;
        for (const s of series.values || []) {
          const v = sampleValue(s);
          const t = s.ts ? parseNfTs(s.ts) : NaN;
          if (v != null && Number.isFinite(t)) {
            m.set(t, v);
            rawSamples++;
          }
        }
      }
      if (rawSamples * Math.max(1, columns.length) > maxCells * 4) {
        rawTooDense = true;
        break;
      }
      done++;
    }

    if (rawTooDense) {
      if (!allowFallback) throw new Error("Raw history exceeds the safe sample limit; shorten the range.");
      const windowSec = pickBucketSecForCap(columns.length, startMs, endMs, maxCells);
      if (!windowSec) {
        throw new Error(`Export exceeds the ${maxCells.toLocaleString()}-cell limit even at 1-day buckets; shorten the range.`);
      }
      const bucketData = await collect({
        points: trendedCols.map((c) => c.point || c),
        startMs,
        endMs,
        windowSec,
        apiFn,
        onProgress,
        isCancelled,
      });
      for (const [k, v] of bucketData) out.set(k, v);
      const tsInfo = await maybeFillTimescale({
        columns, trendedCols, data: out, startMs, endMs, windowSec, timescaleFn, isCancelled,
      });
      return {
        data: out,
        mode: "bucketed",
        windowSec,
        timescaleUsed: tsInfo.used,
        timescaleBucket: tsInfo.bucket,
        timescaleSkippedCols: tsInfo.skippedCols,
        timescaleError: tsInfo.error,
        truncated: tsInfo.truncated,
      };
    }

    // Also fill older span from Timescale if requested range begins earlier than NF retention.
    const fallbackSec = pickBucketSecForCap(columns.length, startMs, endMs, maxCells) || 3600;
    const tsInfo = await maybeFillTimescale({
      columns, trendedCols, data: out, startMs, endMs, windowSec: fallbackSec, timescaleFn, isCancelled,
    });
    return {
      data: out,
      mode: tsInfo.used ? "mixed" : "raw",
      windowSec: tsInfo.used ? fallbackSec : 0,
      timescaleUsed: tsInfo.used,
      timescaleBucket: tsInfo.bucket,
      timescaleSkippedCols: tsInfo.skippedCols,
      timescaleError: tsInfo.error,
      truncated: tsInfo.truncated,
    };
  }

  async function maybeFillTimescale({ columns, trendedCols, data, startMs, endMs, windowSec, timescaleFn, isCancelled }) {
    const empty = { used: false, bucket: null, skippedCols: [], error: "", truncated: false };
    if (typeof timescaleFn !== "function" || !trendedCols.length) return empty;
    let earliestNfMs = Infinity;
    for (const c of trendedCols) {
      const m = data.get(c.uuid);
      if (!m) continue;
      for (const ts of m.keys()) if (ts < earliestNfMs) earliestNfMs = ts;
    }
    const fillUntil = Number.isFinite(earliestNfMs) ? earliestNfMs : endMs;
    if (fillUntil - startMs <= Math.max(windowSec * 2000, 3600e3)) return empty;

    const numericCols = trendedCols.filter((c) => c.kind !== "String" && c.kind !== "Enum");
    const skippedCols = trendedCols.filter((c) => c.kind === "String" || c.kind === "Enum").map((c) => c.dis);
    if (!numericCols.length) return { ...empty, skippedCols };

    if (isCancelled()) throw new Error("cancelled");
    const bucket = bucketLabelForSec(windowSec);
    const tsRes = await timescaleFn({ uuids: numericCols.map((c) => c.uuid), fromMs: startMs, toMs: fillUntil, windowSec, bucket });
    if (!tsRes || tsRes.skipped) return empty;
    if (tsRes.ok === false) return { ...empty, error: tsRes.error || "Timescale history query failed", skippedCols };
    if (tsRes.truncated) {
      throw new Error("Timescale long-range history query exceeded its safe row/byte limit; shorten the range.");
    }
    let used = false;
    const byUuid = new Map(numericCols.map((c) => [c.uuid, c]));
    for (const row of tsRes.rows || []) {
      const col = byUuid.get(row.point_uuid);
      if (!col) continue;
      const m = data.get(col.uuid);
      const t = row.bucket ? Date.parse(row.bucket) : NaN;
      const useMax = methodFor(col.point || col) === "MAX";
      const val = useMax ? (row.max ?? row.avg) : row.avg;
      if (m && Number.isFinite(t) && val != null && Number.isFinite(Number(val)) && !m.has(t)) {
        m.set(t, Number(val));
        used = true;
      }
    }
    return { used, bucket: tsRes.bucket || bucket, skippedCols, error: "", truncated: false };
  }

  function filterColMap(col, rawMap, windowSec) {
    if (!rawMap) return new Map();
    if (col.fddOutputSinceMs == null) return rawMap;
    const width = Math.max(0, Number(windowSec) || 0) * 1e3;
    const firstAllowed = width > 0 ? Math.ceil(col.fddOutputSinceMs / width) * width : col.fddOutputSinceMs;
    const filtered = new Map();
    for (const [ts, val] of rawMap) {
      if (ts >= firstAllowed) filtered.set(ts, val);
    }
    return filtered;
  }

  /**
   * CSV from collected data.
   * When includeEmptyBuckets is true with windowSec > 0, emits every aligned grid timestamp in [startMs, endMs)
   * so shared missing intervals stay visible as blank rows.
   */
  function toCsv({
    columns,
    data,
    mode = "stored",
    system = "imperial",
    startMs = -Infinity,
    endMs = Infinity,
    timezone = null,
    windowSec = 0,
    includeEmptyBuckets = false,
  }) {
    const conv = columns.map((c) => unitFor(c.unit, mode, system));
    const header = [
      "timestamp",
      "timestamp_utc",
      ...uniqueHeaders(columns.map((c, i) => columnName(c.equip, c.dis, conv[i].unit))),
    ];
    const filteredByCol = columns.map((c) => filterColMap(c, data.get(c.uuid), windowSec));
    let actualTimes;
    if (includeEmptyBuckets && windowSec > 0 && Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs) {
      const step = windowSec * 1000;
      const set = new Set();
      const firstBucket = Math.floor(startMs / step) * step;
      for (let b = firstBucket; b < endMs; b += step) {
        if (b + step > startMs) set.add(b);
      }
      for (const m of filteredByCol) {
        for (const t of m.keys()) {
          if (t < endMs && (t >= startMs || t + step > startMs)) set.add(t);
        }
      }
      actualTimes = [...set].sort((a, b) => a - b);
    } else {
      actualTimes = [...new Set(filteredByCol.flatMap((m) => [...m.keys()]))]
        .filter((t) => t < endMs && (t >= startMs || (windowSec > 0 && t + windowSec * 1000 > startMs)))
        .sort((a, b) => a - b);
    }
    const rows = actualTimes.map((bucket) => {
      const t = Math.max(bucket, startMs);
      return [
        localIso(t, timezone),
        utcIso(t),
        ...columns.map((c, i) => {
          const v = filteredByCol[i].get(bucket);
          return v == null ? null : conv[i].convert(v);
        }),
      ];
    });
    const csv = buildCsv(header, rows);
    const cells = rows.length * columns.length;
    if (cells > MAX_CELLS) {
      throw new Error(`CSV has ${cells.toLocaleString()} cells (limit ${MAX_CELLS.toLocaleString()}); shorten the range.`);
    }
    const bytes = utf8ByteLength(csv);
    if (bytes > MAX_BYTES) {
      throw new Error(`CSV is ${(bytes / (1024 * 1024)).toFixed(1)} MiB (limit ${Math.round(MAX_BYTES / (1024 * 1024))} MiB); shorten the range.`);
    }
    return { csv, rows: rows.length, bytes };
  }

  function toJoinedCsv({ columns, data, startMs, endMs, timezone = null, windowSec = 0, mode = "raw" }) {
    return toCsv({
      columns,
      data,
      mode: "stored",
      startMs,
      endMs,
      timezone,
      windowSec,
      includeEmptyBuckets: mode === "bucketed" && windowSec > 0,
    });
  }

  function validate({ nPoints, startMs, endMs, windowSec = 300 }) {
    if (!nPoints) return "Select an equipment item with at least one modeled point.";
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return "Pick a start and an end date-time.";
    if (endMs <= startMs) return "The end must be after the start.";
    if (windowSec > 0) {
      const { rows, cells } = estimateCells(nPoints, startMs, endMs, windowSec);
      if (cells > MAX_CELLS) {
        return `That is about ${cells.toLocaleString()} cells (${nPoints} points x ${rows.toLocaleString()} rows); the limit is ${MAX_CELLS.toLocaleString()}. Shorten the range.`;
      }
    }
    return "";
  }

  const pure = {
    BOM, MAX_CELLS, MAX_BYTES, MAX_CHUNK_DAYS, NF_SAMPLE_LIMIT, RESOLUTIONS, windowFor,
    csvCell, csvLine, buildCsv, localIso, utcIso, inputValue, parseNfTs, chunkRange,
    columnName, uniqueHeaders, unitFor, methodFor, estimateCells, fileName, dataUrl, rawDataUrl,
    sampleValue, exportCandidates, collect, collectJoined, toCsv, toJoinedCsv, validate,
  };

  // ---- DOM (browser only) ----------------------------------------------------------------
  const $ = (id) => /** @type {any} */ (root.document.getElementById(id));
  const st = { mounted: false, busy: false, cur: null, inv: null, bounds: null, rangeTicket: 0, revision: 0 };

  function siteTimeZone() {
    const { model, scope } = st.cur || {};
    const site = model?.sites?.find((s) => (((s.attrs || {}).id) || s.name) === scope?.site);
    return root.resolveSiteTimeZone ? root.resolveSiteTimeZone(site).zone
      : root.chartTimeZone ? root.chartTimeZone(site?.attrs?.tz || site?.attrs?.timezone) : (site?.attrs?.tz || site?.attrs?.timezone || "UTC");
  }

  function rangeState() {
    return root.getChartRangeState ? root.getChartRangeState("export", { defaultPreset: "24h" }) : { preset: "24h" };
  }

  async function refreshRange(state = rangeState()) {
    if (!st.cur || !root.resolveChartSelection) return;
    const ticket = ++st.rangeTicket;
    st.revision++;
    const trendedPts = (st.inv?.trended || []).map((c) => c.point || c);
    const status = $("exRangeStatus");
    if (status) status.textContent = trendedPts.length ? "Resolving history range…" : "No trended points on this equipment.";
    try {
      const resolved = await root.resolveChartSelection(trendedPts, state, { siteTz: siteTimeZone() });
      if (ticket !== st.rangeTicket) return;
      st.bounds = resolved.resolvedBounds;
      if (status) status.textContent = "";
      refreshSummary();
    } catch (e) {
      if (ticket !== st.rangeTicket) return;
      if (status) status.textContent = `Could not resolve history range: ${e.message}`;
      refreshSummary();
    }
  }

  function readRange() {
    return st.bounds ? { startMs: st.bounds.fromMs, endMs: st.bounds.toMs } : { startMs: Date.now() - DAY_MS, endMs: Date.now() };
  }

  function refreshSummary() {
    const inv = st.inv || { columns: [], ioPoints: [], fddPoints: [], trended: [], currentOnly: [] };
    const { startMs, endMs } = readRange();
    const n = inv.columns.length;
    const summaryEl = $("exSummary");
    const goEl = $("exGo");
    if (!inv.equip) {
      if (summaryEl) summaryEl.textContent = "Select one modeled equipment item to export.";
      if (goEl) goEl.disabled = true;
      return;
    }
    const curNote = inv.currentOnly.length ? ` · ${inv.currentOnly.length} current-only/no-history (blank columns)` : "";
    const parts = [
      `${inv.equipLabel}: ${inv.ioPoints.length} I/O + ${inv.fddPoints.length} FDD column${inv.fddPoints.length === 1 ? "" : "s"}${curNote}`,
    ];
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
      if (summaryEl) summaryEl.textContent = "Pick a valid range (end after start).";
      if (goEl) goEl.disabled = true;
      return;
    }
    if (summaryEl) summaryEl.textContent = parts.join("");
    if (goEl) goEl.disabled = st.busy || !n;
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
    if (st.busy || !st.cur) return;
    st.busy = true;
    $("exGo").disabled = true;
    try {
      const frozen = {
        model: st.cur.model,
        scope: { ...st.cur.scope },
        inv: st.inv,
        revision: st.revision,
        tz: siteTimeZone(),
        timescaleFn: st.cur.timescaleHistory || root.ofddTimescaleHistory || null,
      };
      if (!frozen.inv || !frozen.inv.equip) throw new Error("Select a single modeled equipment item first.");
      if (!frozen.inv.trended.length) throw new Error("No trended points on this equipment have recorded history.");
      $("exStatus").textContent = "Resolving history range…";
      const resolved = await root.resolveChartSelection(frozen.inv.trended.map((c) => c.point || c), rangeState(), { siteTz: frozen.tz });
      if (frozen.revision !== st.revision) throw new Error("cancelled because the equipment or range changed");
      st.bounds = resolved.resolvedBounds;
      const { startMs, endMs } = readRange();
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) throw new Error("Pick a valid range.");

      const collected = await collectJoined({
        columns: frozen.inv.columns,
        startMs,
        endMs,
        apiFn: (u) => api(u),
        timescaleFn: frozen.timescaleFn,
        isCancelled: () => frozen.revision !== st.revision,
        onProgress: (i, n) => {
          $("exStatus").textContent = `loading ${Math.min(i + 1, n)} of ${n} request${n === 1 ? "" : "s"}…`;
        },
      });
      if (frozen.revision !== st.revision) throw new Error("cancelled because the equipment or range changed");

      const { csv, rows } = toJoinedCsv({
        columns: frozen.inv.columns,
        data: collected.data,
        startMs,
        endMs,
        timezone: frozen.tz,
        windowSec: collected.windowSec,
        mode: collected.mode,
      });
      if (!rows) {
        $("exStatus").textContent = collected.timescaleError
          ? `No samples returned (${collected.timescaleError}).`
          : "No recorded samples found in that range.";
        return;
      }
      const siteName = (frozen.model.sites.find((s) => idOfRec(s) === frozen.scope.site) || {}).name || frozen.scope.site;
      const name = fileName(`${siteName}_${frozen.inv.equipLabel}`, startMs, endMs, frozen.tz);
      download(name, csv);
      const resNote = collected.mode === "raw"
        ? "exact source timestamps"
        : collected.mode === "bucketed"
          ? `aligned ${collected.windowSec}s bucketed fallback`
          : `exact source timestamps + Timescale ${collected.timescaleBucket} numeric aggregates for older span`;
      const skipNote = collected.timescaleSkippedCols?.length ? ` · text/enum skipped in Timescale aggregate span: ${collected.timescaleSkippedCols.join(", ")}` : "";
      const errNote = collected.timescaleError ? ` · warning: ${collected.timescaleError}` : "";
      $("exStatus").textContent = `saved ${name} · ${rows.toLocaleString()} rows × ${frozen.inv.columns.length} columns (${resNote}${skipNote}${errNote})`;
    } catch (e) {
      $("exStatus").textContent = `export failed: ${e.message}`;
    } finally {
      st.busy = false;
      refreshSummary();
    }
  }

  function mount() {
    st.mounted = true;
    $("exGo").addEventListener("click", () => { run().catch((e) => { $("exStatus").textContent = `export failed: ${e.message}`; }); });
  }

  function render(ctx) {
    st.cur = ctx;
    if (!st.mounted) mount();
    st.inv = exportCandidates(ctx.model, ctx.scope);
    if (root.renderRangeControl && $("exRangeControl")) {
      root.renderRangeControl($("exRangeControl"), {
        key: "export",
        state: rangeState(),
        siteTz: siteTimeZone(),
        onChange: (state) => refreshRange(state),
      });
    }
    refreshSummary();
    refreshRange();
  }

  const exported = { ...pure, render };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  root.ofddExport = exported;
})(typeof globalThis !== "undefined" ? globalThis : this);
