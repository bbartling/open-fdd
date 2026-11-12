// FDD and sensor plots for the Open-FDD NF app (port of the archived central UI's
// fdd-charts.js + sensor-charts.js; chart-parity.json entries ruleResultChart,
// expandFddPlotRoles, withConfirmedFaultLane/oatMeteoFddOption, sensorHealthHeatmap,
// sensorFaultChart, deriveSensorFaultMasks).
//
// All data comes from NF: points bound by fdd.js, history from fetchSeries (NF resamples
// server side), fault lanes from the FDD hook's result points (markers fdd + fault, ruleRef,
// equipRef; result outputs declare fault_pct (%) or fault_hours (h), while sweep timelines
// and input lanes are per sensor. The old central
// computed sensor health server side; here the same checks run on hourly NF aggregates.
//
// Classic script (no import/export/eval). Everything lives in the IIFE below; it exposes
//   fddRulePlot(el, { rule, equipRec, bound, resultPoint, hours })  -> note string
// plus pure helpers fddPlot* (for tests and other views) and registers three RCx views.
// Units: signals reach this file as canonical SI (ctx.series / rcxToSI); sensor health, limits and
// masks all run in SI. Series are mapped to the display system (rcxDisp*) only when a chart is built.
// Needs nf.js, model.js, theme.js, charts.js, fdd.js, rcx.js (and units.js) loaded first.

(() => {
  "use strict";

  const HOUR = 3600e3;

  // ---- small shared helpers (local copies: these files are not ours to edit) ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const finite = (v) => v != null && Number.isFinite(v);
  const equipName = (rec) => ((rec && rec.attrs) || {}).dis || (rec && rec.name) || "";
  const hourFloor = (ms) => Math.floor(ms / HOUR) * HOUR;
  const hourLabel = (ms, siteTz) => new Date(ms).toLocaleString(undefined, { weekday: "short", hour: "numeric", timeZone: siteTz || "UTC" });
  const hiddenX = (gridIndex, show) => ({ type: "time", gridIndex, show, axisPointer: { show: true } });

  // ---- unit families: one stacked grid per family, like the old role-units grouping ---
  const FAMILY_OF_QUANTITY = { temperature: "temp", percent: "pct", pressure: "pressure", flow: "flow", power: "power" };
  /** temp | pct | pressure | flow | power | bool | other:<SI unit or name> for a model point (by quantity, not unit text). */
  function unitFamily(p) {
    if (p.kind === "Bool") return "bool";
    const q = rcxUnits() && p.units ? rcxUnits().quantityOf(p.units) : null;
    if (q && FAMILY_OF_QUANTITY[q]) return FAMILY_OF_QUANTITY[q];
    const u = rcxSiUnit(p).toLowerCase();
    if (u) return `other:${u}`;
    if (has(p, "temp")) return "temp";
    if (has(p, "humidity")) return "pct";
    return `other:${p.name}`;
  }
  const FAMILY_ORDER = ["temp", "pct", "pressure", "flow", "power", "bool"];
  const familyRank = (f) => { const i = FAMILY_ORDER.indexOf(f); return i < 0 ? FAMILY_ORDER.length : i; };

  /** Plot roles for a rule: ECON-1..7 also show the OA damper when it is bound (old expandFddPlotRoles). */
  function fddPlotExpandRoles(ruleId, roles, bound) {
    const out = [...(roles || [])];
    if (!/^ECON-[1-7]$/.test(String(ruleId ?? "").trim().toUpperCase())) return out;
    if (out.includes("oa_damper_pct")) return out;
    if (bound && bound.oa_damper_pct && bound.oa_damper_pct.length) out.push("oa_damper_pct");
    return out;
  }

  // Room rcxWithFaultLane needs under the signal grids (lane + gap + bottom offset + slider).
  const LANE_BLOCK = 110;

  /**
   * Stacked unit-family grids for the rule plot (central's ruleResultChartOption). groups =
   * [{ family, unit, series: [{ name, kind, data }] }], data = [[ms, v], ...]. The fault lane is
   * NOT drawn here: pass the option through rcxWithFaultLane, which appends it as the last grid
   * (heightPx already leaves room when `withLane`). Theme-free: colors come from the theme.
   */
  function fddPlotRuleOption({ title, groups, withLane = false }) {
    const rowH = 90, topPad = 56, bottomPad = 72;
    const list = groups.filter((g) => g.series.some((s) => s.data.length));
    if (!list.length) return { option: null, gridCount: 0, heightPx: 0 };
    const grids = [], xAxis = [], yAxis = [], series = [];
    list.forEach((g, i) => {
      grids.push({ left: 64, right: 24, top: topPad + i * rowH, height: rowH - 12 });
      xAxis.push(hiddenX(i, !withLane && i === list.length - 1));
      yAxis.push({ type: "value", gridIndex: i, scale: true, name: g.unit || g.family.replace(/^other:/, ""), nameTextStyle: { fontSize: 11 } });
      for (const s of g.series) {
        series.push({
          name: s.name, type: "line", xAxisIndex: i, yAxisIndex: i, showSymbol: false, connectNulls: false,
          step: s.kind === "Bool" ? "end" : false, lineStyle: { width: 1.6, ...(s.color ? { color: s.color } : {}) }, data: s.data,
        });
      }
    });
    return {
      option: {
        title: { text: title, left: 8, top: 4, textStyle: { rich: FDD_RULE_RICH } },
        legend: { top: 26, type: "scroll" },
        tooltip: { trigger: "axis", axisPointer: { type: "line", link: [{ xAxisIndex: "all" }] } },
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        grid: grids, xAxis, yAxis, series,
      },
      gridCount: grids.length,
      heightPx: Math.max(320, topPad + list.length * rowH + bottomPad + (withLane ? LANE_BLOCK : 0)),
    };
  }

  /** BAS vs web OAT (web dashed) in one grid; add the lane with rcxWithFaultLane. */
  function fddPlotOatOption({ title, bas, web, unit, withLane = false }) {
    const topPad = 56, sigH = 260;
    return {
      option: {
        title: { text: title, left: 8, top: 4 },
        legend: { top: 26 },
        tooltip: { trigger: "axis", axisPointer: { type: "line", link: [{ xAxisIndex: "all" }] } },
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        grid: [{ left: 64, right: 24, top: topPad, height: sigH }],
        xAxis: [hiddenX(0, !withLane)],
        yAxis: [{ type: "value", gridIndex: 0, scale: true, name: unit || "", nameTextStyle: { fontSize: 11 } }],
        series: [
          { name: bas.name, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, connectNulls: false, lineStyle: { width: 1.6 }, data: bas.data },
          { name: web.name, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, connectNulls: false, step: "end",
            lineStyle: { width: 1.6, type: "dashed" }, data: web.data },
        ],
      },
      heightPx: topPad + sigH + 72 + (withLane ? LANE_BLOCK : 0),
    };
  }

  // ---- sensor health -------------------------------------------------------------------
  const HEALTH = { OK: 0, STALE: 1, FLATLINE: 2, RANGE: 3 };
  const HEALTH_LABELS = ["ok", "stale", "flatline", "out of range"];

  // Plausibility limits in SI (degC, %RH, Pa) — what a working sensor of that family can physically
  // report: -40..65.556 C (-40..150 F), -2..102 %, -1245.4..3736.3 Pa (-5..15 inH2O).
  const SENSOR_LIMITS = { temp: { min: -40, max: 65.556 }, pct: { min: -2, max: 102 }, pressure: { min: -1245.4, max: 3736.3 } };

  /**
   * Per-hour health of one sensor, aligned to `grid` (hour-start ms list).
   * series = { avg, min, max, count }: Map(hourStart ms -> value) from NF AVERAGE/MIN/MAX/COUNT, in SI.
   * opts: { family, staleHours = 2, flatTol = 0.055556, minCount = 3, limits }
   * Thresholds (defaults mirror fdd-catalog SV-STALE / SV-FLATLINE / SV-RANGE parameters):
   *   out of range  an hour's MIN or MAX is outside the family's plausibility limits (priority);
   *   flatline      >= minCount samples in the hour and (MAX - MIN) <= flatTol (SI units);
   *   stale         a run of >= staleHours consecutive hours with no samples after the sensor's
   *                 first sample (shorter gaps stay null = no verdict, leading hours before
   *                 the first sample are null = no history yet);
   *   ok            data present, none of the above.
   * Returns [code|null, ...] with codes from HEALTH.
   */
  function fddPlotHealthStates(grid, series, opts = {}) {
    const { family = "temp", staleHours = 2, flatTol = 0.055556, minCount = 3 } = opts;
    const limits = opts.limits || SENSOR_LIMITS[family] || null;
    const out = grid.map(() => null);
    const present = grid.map((t) => series.avg.has(t));
    const first = present.indexOf(true);
    if (first < 0) return out;
    for (let i = first; i < grid.length; i++) {
      if (!present[i]) continue;
      const t = grid[i];
      const lo = series.min && series.min.has(t) ? series.min.get(t) : series.avg.get(t);
      const hi = series.max && series.max.has(t) ? series.max.get(t) : series.avg.get(t);
      const n = series.count ? series.count.get(t) : null;
      if (limits && (lo < limits.min || hi > limits.max)) out[i] = HEALTH.RANGE;
      else if (finite(n) && n >= minCount && finite(lo) && finite(hi) && hi - lo <= flatTol) out[i] = HEALTH.FLATLINE;
      else out[i] = HEALTH.OK;
    }
    for (let i = first; i < grid.length;) {
      if (present[i]) { i++; continue; }
      let j = i;
      while (j < grid.length && !present[j]) j++;
      if (j - i >= staleHours) for (let k = i; k < j; k++) out[k] = HEALTH.STALE;
      i = j;
    }
    return out;
  }

  /** Heatmap: one row per sensor, one column per hour, categorical health state. */
  function fddPlotHealthOption({ title, rows, hours, siteTz }) {
    if (!rows.length || !hours.length) return null;
    const pal = typeof palette === "function" ? palette() : [];
    const colors = [pal[3] || "#16a34a", pal[1] || "#ea580c", pal[5] || "#2563eb", FAULT_LANE.lineStyle.color];
    const data = [];
    rows.forEach((r, y) => r.states.forEach((s, x) => { if (s != null) data.push([x, y, s]); }));
    return {
      title: { text: title, left: 8, top: 4 },
      tooltip: {
        position: "top",
        formatter: (x) => `${esc(rows[x.value[1]].label)}<br>${esc(hourLabel(hours[x.value[0]], siteTz))}: <b>${esc(HEALTH_LABELS[x.value[2]])}</b>`,
      },
      grid: { left: 150, right: 20, top: 44, bottom: 86 },
      xAxis: { type: "category", data: hours.map((t) => hourLabel(t, siteTz)), splitArea: { show: false } },
      yAxis: { type: "category", data: rows.map((r) => r.label), inverse: true },
      visualMap: {
        type: "piecewise", dimension: 2, orient: "horizontal", left: "center", bottom: 28,
        pieces: HEALTH_LABELS.map((label, value) => ({ value, label, color: colors[value] })),
      },
      dataZoom: false,
      series: [{ type: "heatmap", data }],
    };
  }

  /**
   * Per-sample sensor fault masks (port of deriveSensorFaultMasks): 1 = flagged.
   *   SV-FLATLINE  every `flatlineWindow` samples in a row identical (std ~ 0, >= minSlice finite)
   *   SV-SPIKE     |v - mean| > spikeZ * std (whole series)
   *   SV-RANGE     outside opts.bounds {min, max} when given, else |v - mean| > rangeZ * std
   * Defaults: flatlineWindow 12, minSlice max(5, 60% of window), spikeZ 4, rangeZ 3.
   */
  function fddPlotSensorMasks(values, opts = {}) {
    const win = opts.flatlineWindow ?? 12;
    const spikeZ = opts.spikeZ ?? 4;
    const rangeZ = opts.rangeZ ?? 3;
    const minSlice = opts.minSlice ?? Math.max(5, Math.floor(win * 0.6));
    const fin = values.filter(finite);
    const mean = fin.length ? fin.reduce((a, b) => a + b, 0) / fin.length : 0;
    const std = fin.length > 1 ? Math.sqrt(fin.reduce((a, v) => a + (v - mean) ** 2, 0) / fin.length) : 0;
    const flatline = values.map(() => 0), spike = values.map(() => 0), range = values.map(() => 0);
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (!finite(v)) continue;
      if (opts.bounds) { if (v < opts.bounds.min || v > opts.bounds.max) range[i] = 1; }
      else if (std > 0 && Math.abs(v - mean) > rangeZ * std) range[i] = 1;
      if (std > 0 && Math.abs(v - mean) > spikeZ * std) spike[i] = 1;
      if (i + 1 >= win) {
        const slice = values.slice(i + 1 - win, i + 1).filter(finite);
        if (slice.length >= minSlice) {
          const m = slice.reduce((a, b) => a + b, 0) / slice.length;
          const s = Math.sqrt(slice.reduce((a, x) => a + (x - m) ** 2, 0) / slice.length);
          if (s <= 1e-9) for (let j = i + 1 - win; j <= i; j++) flatline[j] = 1;
        }
      }
    }
    return { "SV-FLATLINE": flatline, "SV-SPIKE": spike, "SV-RANGE": range };
  }

  /**
   * One sensor line (old sensorFaultChartOption); its mask lanes go through rcxWithFaultLane
   * as `lanes` = [{ name, data: [[ms, 0|1], ...] }] (see fddPlotMaskLanes).
   */
  function fddPlotSensorFaultOption({ title, name, yTitle, t, y, nLanes = 0 }) {
    if (!y.some(finite)) return null;
    const topPad = 56, sigH = 200;
    return {
      option: {
        title: { text: title, left: 8, top: 4 }, legend: { top: 26 },
        tooltip: { trigger: "axis", axisPointer: { type: "line", link: [{ xAxisIndex: "all" }] } },
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        grid: [{ left: 64, right: 24, top: topPad, height: sigH }],
        xAxis: [hiddenX(0, !nLanes)],
        yAxis: [{ type: "value", gridIndex: 0, scale: true, name: yTitle || "value" }],
        series: [{ name, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, connectNulls: false,
          lineStyle: { width: 1.4 }, data: t.map((x, i) => [x, y[i]]) }],
      },
      heightPx: topPad + sigH + 72 + nLanes * 34 + (nLanes ? 76 : 0),
    };
  }

  /** Masks {lane: 0|1[]} + timestamps -> lanes for rcxWithFaultLane. */
  const fddPlotMaskLanes = (t, masks) => Object.entries(masks).map(([name, m]) => ({ name, data: t.map((x, i) => [x, m[i] ? 1 : 0]) }));

  // ---- drawing ----------------------------------------------------------------------------
  function draw(el, built, name) {
    el.style.height = `${built.heightPx}px`;
    if (el.dataset) el.dataset.sized = "1";        // the option already leaves room for its lanes: the tab must not add more
    const chart = ofddChart(el);
    ofddRender(chart, built.option, name);
    chart.resize();
  }

  const hourly = (arr) => new Map((arr || []).map(([t, v]) => [hourFloor(t), v]));

  /** Latest persisted sweep result, in fault hours per assessed sensor role. */
  function fddPlotSensorFaultHours(point) {
    const attrs = point?.rec?.attrs || {};
    if (!attrs.fddSensorFaultHours || attrs.fddStatus === "stale" || attrs.fddStatus === "not-assessed") return "";
    try {
      return Object.entries(JSON.parse(attrs.fddSensorFaultHours))
        .filter(([, hours]) => typeof hours === "number" && Number.isFinite(hours) && hours >= 0)
        .map(([role, hours]) => `${role} ${Number(hours.toFixed(3))} h`).join(", ");
    } catch (_) {
      return "";
    }
  }

  /**
   * Per-rule result plot: bound inputs grouped by unit family plus either the equipment fault
   * lane or one sensor-specific lane per sweep input. Returns a short note.
   */
  /**
   * With `model`, the lane is rcxFaultData(model, equipRec, rule.id, hours): the hook's per-timestamp confirmed-fault
   * timeline (1 / 0 / gap), falling back (labelled approximate, drawn dashed) to the rolling fault_pct point.
   * Without `model` only the caller's `resultPoint` is available, so the lane is that fallback.
   * @param {HTMLElement} el @param {{rule?: any, equipRec?: any, bound?: Record<string, any[]>, resultPoint?: any, model?: any, hours?: number, range?: any, siteTz?: string}} [o]
   */
  async function fddRulePlot(el, { rule, equipRec, bound = {}, resultPoint = null, model = null, hours = 168, range = null, siteTz = "UTC" } = {}) {
    const wanted = [...new Set([...(rule.required_roles || []), ...(rule.optional_roles || [])])];
    const roles = fddPlotExpandRoles(rule.id, wanted, bound).filter((r) => bound[r] && bound[r].length);
    const sensorSweep = /^SV-(RATE|RANGE|FLATLINE|SPIKE|STALE)$/.test(String(rule.id || ""));
    const sensorResults = sensorSweep && model ? rcxSensorResultPoints(model, equipRec, rule.id) : [];
    if (!roles.length && !sensorResults.length) return "No bound input points for this rule on this equip.";
    const pointRoles = new Map();
    const boundPoints = sensorSweep ? roles.flatMap((r) => bound[r].map((p) => {
      if (!pointRoles.has(p.uuid)) pointRoles.set(p.uuid, r);
      return p;
    })) : roles.map((r) => bound[r][0]);
    if (sensorResults.length && model) {
      for (const result of sensorResults) {
        const attrs = result.rec?.attrs || {}, ref = String(attrs.sensorRef || "");
        const input = model.points.find((p) => String(p.uuid) === ref && has(p, "point"));
        if (input && !pointRoles.has(input.uuid)) pointRoles.set(input.uuid, attrs.roleRef || "sensor");
        if (input) boundPoints.push(input);
      }
    }
    const pts = sensorSweep ? [...new Map(boundPoints.map((p) => [p.uuid, p])).values()] : boundPoints;
    const sensorResultByRef = new Map(sensorResults.map((p) => [String((p.rec.attrs || {}).sensorRef || ""), p]));
    const windowSec = pickWindow(hours);
    const sigRaw = range ? (await fetchRange(pts, range, { windowSec, minWindowSec: windowSec, siteTz, preserveWindow: true })).series
      : await fetchSeries(pts, hours, { windowSec });
    let lane, sensorLanes = [];
    if (sensorResults.length) {
      sensorLanes = await Promise.all(pts.map(async (p) => {
        const attrs = p.rec?.attrs || {}, ref = String(p.uuid), res = sensorResultByRef.get(ref);
        const label = `${pointRoles.get(ref) || attrs.roleRef || "sensor"} · ${p.dis || p.name}`;
        const data = await rcxFaultData(model, equipRec, rule.id, hours, { sensorRef: ref, range, siteTz });
        const samples = data.map((x) => [...x]);
        Object.defineProperties(samples, { source: { value: data.source }, approximate: { value: !!data.approximate } });
        return { point: p, result: res, label, data: samples };
      }));
      lane = [];
    } else {
      if (model) lane = await rcxFaultData(model, equipRec, rule.id, hours, { range, siteTz });
      else if (resultPoint) {
        const data = range ? (await fetchRange([resultPoint], range, { method: "MAX", windowSec: 3600, minWindowSec: 3600, siteTz, preserveWindow: true })).series
          : await fetchSeries([resultPoint], hours, { method: "MAX", windowSec: 3600 });
        lane = rcxFaultLaneFromResult(rcxCurrentOutputSeries(resultPoint, data.get(resultPoint.uuid) || [], 3600));
      } else lane = rcxFaultLaneFromResult(null, true);
    }
    const groups = new Map();
    pts.forEach((p) => {
      const role = pointRoles.get(p.uuid) || roles.find((r) => bound[r].includes(p)) || "sensor";
      const fam = unitFamily(p);
      // history arrives in the point's own unit: SI first, then display units for the chart
      const si = rcxSiUnit(p), unit = rcxDisp(0, si).unit;
      const g = groups.get(fam) || { family: fam, unit, series: [] };
      const sensorResult = sensorResultByRef.get(String(p.uuid));
      const status = sensorResult?.rec?.attrs?.fddStatus;
      const color = status === "fault" ? (FAULT_LANE.lineStyle.color || "#dc2626")
        : status === "ok" ? "#16a34a" : status === "stale" ? "#64748b" : status === "not-assessed" ? "#94a3b8" : null;
      const seriesName = sensorSweep ? `${role} · ${p.dis || p.name}${unit ? ` (${unit})` : ""}`
        : `${role}${unit ? ` (${unit})` : ""}`;
      g.series.push({ name: seriesName, kind: p.kind, color,
        data: rcxDispSeries(rcxToSI(sigRaw.get(p.uuid) || [], p), si) });
      groups.set(fam, g);
    });
    const built = fddPlotRuleOption({
      title: fddRuleRich(fddRuleTitle(rule), rule.id, equipName(equipRec)),
      groups: [...groups.values()].sort((a, b) => familyRank(a.family) - familyRank(b.family) || a.family.localeCompare(b.family)),
      withLane: lane.length > 0 || sensorLanes.length > 0,
    });
    if (!built.option) return "No history for the bound inputs in this range.";
    built.option = rcxWithFaultLane(built.option, sensorLanes.length
      ? sensorLanes.map((x) => ({ name: `${rule.id} · ${x.label}`, data: x.data }))
      : [{ name: rule.id, data: lane }]);
    const axisLabel = (ms) => new Date(ms).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: siteTz || "UTC" });
    for (const axis of (Array.isArray(built.option.xAxis) ? built.option.xAxis : [built.option.xAxis])) {
      if (axis?.type === "time") {
        axis.axisLabel = { ...(axis.axisLabel || {}), formatter: axisLabel };
        if (range?.resolvedBounds) { axis.min = range.resolvedBounds.fromMs; axis.max = range.resolvedBounds.toMs; }
      }
    }
    draw(el, built, `fdd_${rule.id}_${equipName(equipRec)}`);
    const scores = fddPlotSensorFaultHours(resultPoint || (model && rcxResultPoint(model, equipRec, rule.id)));
    const sensorNote = scores && !sensorResults.length ? ` · latest sensor fault hours: ${scores}` : "";
    if (sensorLanes.length) {
      const faulted = sensorLanes.filter((x) => x.result?.rec?.attrs?.fddStatus === "fault").length;
      return `${pts.length} input sensors · ${sensorLanes.length} per-sensor timelines · ${faulted} faulted`;
    }
    if (lane.source === "none") return `${roles.length} inputs · no result point yet (the FDD hook has not written ${rule.id} for this equip)`;
    const confirmed = lane.filter(([, f]) => f === 1).length, gaps = lane.filter(([, f]) => f == null).length;
    if (lane.source === "timeline") {
      return `${roles.length} inputs · confirmed fault in ${confirmed} of ${lane.length - gaps} assessed samples`
        + (gaps ? ` · ${gaps} gap${gaps === 1 ? "" : "s"} (not assessed)` : "") + sensorNote;
    }
    return `${roles.length} inputs · approximate: fault in ${confirmed} of ${lane.length} hourly results (no per-timestamp timeline for ${rule.id} yet)` + sensorNote;
  }

  /** Fallback lane from a rolling fault_pct series (no timeline point): [[ms, 1|0]], nulls kept, tagged approximate. */
  function rcxFaultLaneFromResult(arr, none = false) {
    const lane = (arr || []).map(([t, v]) => [t, v == null ? null : v > 0 ? 1 : 0]);
    return Object.defineProperties(lane, { source: { value: none ? "none" : "fault_pct" }, approximate: { value: !none } });
  }

  // ---- views --------------------------------------------------------------------------------
  // FDD-tab charts all share one look: signal lines on top, a bool fault lane (0/1 step) at the bottom
  // (rcxWithFaultLane). The old "Weather · BAS vs web outside air temp (OAT-METEO)" view is gone: the same
  // comparison is the FDD chart "BAS vs web outdoor-air temperature" (rcx-overview.js, tab "fdd").

  // Temperature / humidity / pressure roles the SV-* rules check (all exist in fdd-catalog roles).
  const SENSOR_ROLES = ["oa_t", "mat", "zone_t", "rat", "sat", "chw_supply_t", "chw_return_t", "hw_supply_t",
    "hw_return_t", "oa_h", "ra_h", "zone_rh", "ma_h", "sa_h", "duct_static"];

  /** Bound sensor points for an equip: [{ role, p }] in SENSOR_ROLES order. */
  const sensorsOf = (ctx, eq) => SENSOR_ROLES.map((role) => ({ role, p: ctx.first(eq, role) })).filter((s) => s.p);

  // ---- sensor sweep lanes: SV Range, Rate, Spike, Stale (always all four) ----------------------
  // Open-FDD owns the sweep science. The chart shows the FDD hook's own per-sensor results (timeline points of SV-RANGE,
  // SV-RATE, SV-SPIKE, SV-STALE) whenever the hook has written any. Only without hook results it ESTIMATES the lanes in the
  // browser, from hourly aggregates, with the SI sweep limits of open_fdd/data/sensor_sweep_limits.json (plot-spec-data.js,
  // key sweep_limits), and the chart says "estimated in browser". No threshold below is invented here.
  const SWEEP_LANES = [
    { rule: "SV-RANGE", name: "SV Range" }, { rule: "SV-RATE", name: "SV Rate" },
    { rule: "SV-SPIKE", name: "SV Spike" }, { rule: "SV-STALE", name: "SV Stale" },
  ];
  const SWEEP_QUANTITY = { temp: "absolute_temperature", pct: "relative_humidity", pressure: "air_pressure" };

  /**
   * Sweep limits (SI) of one sensor from the limits file: { lo, hi, spike_delta, rate_per_h, stale_s } (a field is null when
   * the file has no value: that lane then has no verdict). Per-role entry first (catalog role name, e.g. "outside-air-temp"),
   * else the quantity fallback of the unit family; null when neither exists.
   */
  function fddPlotSweepLimits(roleName, family, doc) {
    const d = doc || (globalThis.ofddPlotSpecData && globalThis.ofddPlotSpecData.sweep_limits);
    if (!d) return null;
    const def = d.defaults || {}, entry = (d.roles || []).find((r) => r.role === roleName);
    const fb = (d.quantity_fallback || {})[SWEEP_QUANTITY[family]];
    const src = entry || fb;
    if (!src) return null;
    const rate = entry ? entry.rate_per_h : (family === "temp" ? def.rate_per_h : null);
    return { lo: src.lo, hi: src.hi, spike_delta: src.spike_delta, rate_per_h: rate == null ? null : rate, stale_s: def.stale_s ?? null, source: entry ? "role" : "quantity" };
  }

  /**
   * The four sweep lane masks of one sensor ESTIMATED from an hourly series: { "SV-RANGE", "SV-RATE", "SV-SPIKE", "SV-STALE" },
   * each [[ms, 1|0|null]] (null = no verdict: before the first sample, or no sample in that hour). arr = [[ms, v]] (SI),
   * limits = fddPlotSweepLimits(...), opts = { firstMs, lastMs }.
   * RANGE outside [lo, hi]; SPIKE |step to the previous sample| > spike_delta; RATE |step| per hour > rate_per_h; STALE a run of
   * >= stale_s of hours without any sample after the first. A limit the file leaves null gives that lane no verdict (0 / ok).
   */
  function fddPlotSweepLanes(arr, limits, opts = {}) {
    const lim = limits || {};
    const staleHours = finite(lim.stale_s) ? lim.stale_s / 3600 : Infinity;
    const pts = (arr || []).filter(([, v]) => finite(v)).map(([t, v]) => [hourFloor(t), v]);
    const out = Object.fromEntries(SWEEP_LANES.map((l) => [l.rule, []]));
    if (!pts.length) return out;
    const first = opts.firstMs != null ? Math.min(hourFloor(opts.firstMs), pts[0][0]) : pts[0][0];
    const last = opts.lastMs != null ? Math.max(hourFloor(opts.lastMs), pts[pts.length - 1][0]) : pts[pts.length - 1][0];
    const grid = [];
    for (let t = first; t <= last; t += HOUR) grid.push(t);
    const at = new Map(pts);
    const vals = grid.map((t) => (at.has(t) ? at.get(t) : null));
    const firstIdx = vals.findIndex(finite);
    const stale = grid.map(() => 0);
    for (let i = firstIdx; i < grid.length;) {
      if (finite(vals[i])) { i++; continue; }
      let j = i;
      while (j < grid.length && !finite(vals[j])) j++;
      if (j - i >= staleHours) for (let k = i; k < j; k++) stale[k] = 1;
      i = j;
    }
    let prev = null;
    grid.forEach((t, i) => {
      const v = vals[i], has = finite(v), pre = i < firstIdx;
      const step = has && prev ? Math.abs(v - prev.v) : null;
      const range = finite(lim.lo) && finite(lim.hi) && (v < lim.lo || v > lim.hi) ? 1 : 0;
      const spike = step != null && finite(lim.spike_delta) && step > lim.spike_delta ? 1 : 0;
      const rate = step != null && finite(lim.rate_per_h) && step / ((t - prev.t) / HOUR) > lim.rate_per_h ? 1 : 0;
      if (has) prev = { t, v };
      out["SV-RANGE"].push([t, pre || !has ? null : range]);
      out["SV-RATE"].push([t, pre || !has ? null : rate]);
      out["SV-SPIKE"].push([t, pre || !has ? null : spike]);
      out["SV-STALE"].push([t, pre ? null : stale[i]]);
    });
    return out;
  }

  /** Total flagged samples over the four lanes (the "worst sensor" score). */
  const fddPlotSweepScore = (lanes) => Object.values(lanes).reduce((a, l) => a + l.reduce((x, [, f]) => x + (f === 1 ? 1 : 0), 0), 0);

  /** Pick the sensor with the most sweep faults. cands = [{ score, ... }]; ties keep the first. */
  const fddPlotWorstSensor = (cands) => cands.reduce((w, c) => (!w || c.score > w.score ? c : w), null);

  /** Index of the hook's per-sensor sweep results: Map(sensor point uuid -> latest fault output summed over the four rules). */
  function fddPlotHookSensors(model) {
    const rules = new Set(SWEEP_LANES.map((l) => l.rule)), out = new Map();
    for (const r of (model && model.points) || []) {
      const a = (r.rec && r.rec.attrs) || {};
      if (!rules.has(a.ruleRef) || !a.sensorRef || !has(r, "fdd") || !has(r, "fault")) continue;
      const v = Number(r.latest && (r.latest.double ?? r.latest.real));
      out.set(String(a.sensorRef), (out.get(String(a.sensorRef)) || 0) + (Number.isFinite(v) && v > 0 ? v : 0));
    }
    return out;
  }

  rcxView({
    id: "fdd-sensor-fault", group: "Sensors", title: "Sensor validation: the sensor with the most sweep faults",
    tab: "fdd", roles: { required: [], optional: SENSOR_ROLES }, scope: "site", minEquips: 1, hours: 168,
    async render(el, ctx) {
      const cands = ctx.equips.flatMap((eq) => sensorsOf(ctx, eq).map((s) => ({ eq, ...s })));
      if (!cands.length) return "No temperature, humidity or pressure sensor roles are bound on the equipment in scope.";
      const hook = fddPlotHookSensors(ctx.model);
      const hooked = cands.filter((c) => hook.has(String(c.p.uuid)));
      const bounds = ctx.range && ctx.range.resolvedBounds;
      const span = bounds && Number.isFinite(bounds.fromMs) && Number.isFinite(bounds.toMs) ? { firstMs: bounds.fromMs, lastMs: bounds.toMs - 1 } : {};
      let worst, lanes, scored, source;
      if (hooked.length) {
        // the hook's results: the sensor with the largest fault output, its four timelines as written by the hook
        source = "FDD hook results";
        scored = hooked.length;
        worst = hooked.reduce((w, c) => (!w || hook.get(String(c.p.uuid)) > hook.get(String(w.p.uuid)) ? c : w), null);
        const data = await ctx.series([worst.p], { windowSec: 3600 });
        worst.arr = data.get(worst.p.uuid) || [];
        if (!worst.arr.length) return "No history in this range.";
        const t0 = worst.arr[0][0], t1 = worst.arr[worst.arr.length - 1][0];
        lanes = {};
        for (const l of SWEEP_LANES) {
          const lane = await rcxFaultData(ctx.model, worst.eq, l.rule, ctx.hours, { sensorRef: worst.p.uuid, range: ctx.range, siteTz: ctx.siteTz });
          lanes[l.rule] = lane.length ? [...lane] : [[t0, null], [t1, null]];     // a rule the hook has not written yet: an empty lane, still drawn
        }
        worst.score = fddPlotSweepScore(lanes);
      } else {
        source = "estimated in browser";
        const data = await ctx.series(cands.map((s) => s.p), { windowSec: 3600 });
        const ranked = [];
        for (const c of cands) {
          const arr = data.get(c.p.uuid) || [];
          if (!arr.length) continue;
          const roleName = ctx.catalog && ctx.catalog.roles && ctx.catalog.roles[c.role] ? ctx.catalog.roles[c.role].name : c.role;
          const l = fddPlotSweepLanes(arr, fddPlotSweepLimits(roleName, unitFamily(c.p)), span);
          ranked.push({ ...c, arr, lanes: l, score: fddPlotSweepScore(l) });
        }
        worst = fddPlotWorstSensor(ranked);
        if (!worst) return "No history in this range.";
        scored = ranked.length;
        lanes = worst.lanes;
      }
      const label = `${worst.p.dis || worst.p.name} (${equipName(worst.eq.rec || worst.eq)})`;
      const hours = [...new Set(worst.arr.map(([t]) => hourFloor(t)))].sort((a, b) => a - b);
      const y = new Map(worst.arr.map(([t, v]) => [hourFloor(t), v]));
      const disp = ctx.dispSeries(hours.map((t) => [t, y.has(t) ? y.get(t) : null]), ctx.siUnit(worst.p));
      const built = fddPlotSensorFaultOption({
        title: `Sensor validation · ${label} · ${source}`, name: label, yTitle: ctx.unit(worst.p),
        t: disp.map(([t]) => t), y: disp.map(([, v]) => v), nLanes: SWEEP_LANES.length,
      });
      if (!built) return "No history in this range.";
      built.option.legend = { top: 40, type: "scroll" };
      built.option.title.subtext = `Worst of ${scored} sensor${scored === 1 ? "" : "s"} in scope (${source}): ${worst.score} flagged sample${worst.score === 1 ? "" : "s"} across the four sweep lanes`;
      built.option.title.subtextStyle = { fontSize: 11 };
      built.option.grid[0].top += 28;
      delete built.option.grid[0].height;           // the signal grid stretches between the title and the lanes: the chart fills its pane
      built.heightPx = 84 + 250 + SWEEP_LANES.length * 34 + 70;
      built.option = rcxWithFaultLane(built.option, SWEEP_LANES.map((l) => ({ name: l.name, data: lanes[l.rule] })));
      draw(el, built, `sensor_fault_${worst.p.name}`);
      return `${label}: ${worst.score} flagged samples · lanes: ${SWEEP_LANES.map((l) => l.name).join(", ")} · `
        + (source === "FDD hook results" ? "from the FDD hook's per-sensor timelines"
          : "estimated in browser from hourly aggregates with the limits of sensor_sweep_limits.json (the FDD hook has no sweep results yet)");
    },
  });

  Object.assign(globalThis, {
    fddRulePlot, fddPlotMaskLanes, fddPlotExpandRoles, fddPlotRuleOption, fddPlotOatOption, fddPlotHealthStates,
    fddPlotHealthOption, fddPlotSensorMasks, fddPlotSensorFaultOption, fddPlotUnitFamily: unitFamily, fddPlotLimits: SENSOR_LIMITS,
    fddPlotSweepLanes, fddPlotSweepLimits, fddPlotHookSensors, fddPlotSweepScore, fddPlotWorstSensor, FDD_SWEEP_LANES: SWEEP_LANES,
  });
})();
