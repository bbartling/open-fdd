// FDD and sensor plots for the Open-FDD NF app (port of the archived central UI's
// fdd-charts.js + sensor-charts.js; chart-parity.json entries ruleResultChart,
// expandFddPlotRoles, withConfirmedFaultLane/oatMeteoFddOption, sensorHealthHeatmap,
// sensorFaultChart, deriveSensorFaultMasks).
//
// All data comes from NF: points bound by fdd.js, history from fetchSeries (NF resamples
// server side), fault lanes from the FDD hook's result points (markers fdd + fault, ruleRef,
// equipRef; value = fault % of covered time over 24 h, trended hourly). The old central
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
  const hourLabel = (ms) => new Date(ms).toLocaleString(undefined, { weekday: "short", hour: "numeric" });
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
          step: s.kind === "Bool" ? "end" : false, lineStyle: { width: 1.6 }, data: s.data,
        });
      }
    });
    return {
      option: {
        title: { text: title, left: 8, top: 4 },
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
  function fddPlotHealthOption({ title, rows, hours }) {
    if (!rows.length || !hours.length) return null;
    const pal = typeof palette === "function" ? palette() : [];
    const colors = [pal[3] || "#16a34a", pal[1] || "#ea580c", pal[5] || "#2563eb", FAULT_LANE.lineStyle.color];
    const data = [];
    rows.forEach((r, y) => r.states.forEach((s, x) => { if (s != null) data.push([x, y, s]); }));
    return {
      title: { text: title, left: 8, top: 4 },
      tooltip: {
        position: "top",
        formatter: (x) => `${esc(rows[x.value[1]].label)}<br>${esc(hourLabel(hours[x.value[0]]))}: <b>${esc(HEALTH_LABELS[x.value[2]])}</b>`,
      },
      grid: { left: 150, right: 20, top: 44, bottom: 86 },
      xAxis: { type: "category", data: hours.map(hourLabel), splitArea: { show: false } },
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
    const chart = ofddChart(el);
    ofddRender(chart, built.option, name);
    chart.resize();
  }

  const hourly = (arr) => new Map((arr || []).map(([t, v]) => [hourFloor(t), v]));

  /**
   * Per-rule result plot: the rule's bound input signals grouped by unit family plus a fault
   * lane from the hook's result point. Returns a short note.
   */
  /** @param {HTMLElement} el @param {{rule?: any, equipRec?: any, bound?: Record<string, any[]>, resultPoint?: any, hours?: number}} [o] */
  async function fddRulePlot(el, { rule, equipRec, bound = {}, resultPoint = null, hours = 168 } = {}) {
    const wanted = [...new Set([...(rule.required_roles || []), ...(rule.optional_roles || [])])];
    const roles = fddPlotExpandRoles(rule.id, wanted, bound).filter((r) => bound[r] && bound[r].length);
    if (!roles.length) return "No bound input points for this rule on this equip.";
    const pts = roles.map((r) => bound[r][0]);
    const windowSec = pickWindow(hours);
    const [sigRaw, res] = await Promise.all([
      fetchSeries(pts, hours, { windowSec }),
      // Same data as rcxFaultData, but from the result point the caller already resolved.
      resultPoint ? fetchSeries([resultPoint], hours, { method: "MAX", windowSec: 3600 }) : Promise.resolve(null),
    ]);
    const groups = new Map();
    roles.forEach((role, i) => {
      const p = pts[i];
      const fam = unitFamily(p);
      // history arrives in the point's own unit: SI first, then display units for the chart
      const si = rcxSiUnit(p), unit = rcxDisp(0, si).unit;
      const g = groups.get(fam) || { family: fam, unit, series: [] };
      g.series.push({ name: `${role}${unit ? ` (${unit})` : ""}`, kind: p.kind,
        data: rcxDispSeries(rcxToSI(sigRaw.get(p.uuid) || [], p), si) });
      groups.set(fam, g);
    });
    const lane = res ? (res.get(resultPoint.uuid) || []).map(([t, v]) => [t, v > 0 ? 1 : 0]) : [];
    const built = fddPlotRuleOption({
      title: `${rule.id} · ${equipName(equipRec)}`,
      groups: [...groups.values()].sort((a, b) => familyRank(a.family) - familyRank(b.family) || a.family.localeCompare(b.family)),
      withLane: lane.length > 0,
    });
    if (!built.option) return "No history for the bound inputs in this range.";
    built.option = rcxWithFaultLane(built.option, [{ name: rule.id, data: lane }]);
    draw(el, built, `fdd_${rule.id}_${equipName(equipRec)}`);
    if (!resultPoint) return `${roles.length} inputs · no result point yet (the FDD hook has not written ${rule.id} for this equip)`;
    return `${roles.length} inputs · fault in ${lane.filter(([, f]) => f).length} of ${lane.length} hourly results`;
  }

  // ---- views --------------------------------------------------------------------------------
  rcxView({
    id: "fdd-oat-meteo", group: "Weather", title: "BAS vs web outside air temp (OAT-METEO)",
    roles: { required: ["oa_t", "web_oa_t"], optional: [] }, scope: "equip", hours: 168,
    async render(el, ctx) {
      const eq = ctx.equips[0];
      const bas = ctx.first(eq, "oa_t"), web = ctx.first(eq, "web_oa_t");
      const [sig, lane] = await Promise.all([ctx.series([bas, web]), rcxFaultData(ctx.model, eq.id, "OAT-METEO", ctx.hours)]);
      const built = fddPlotOatOption({
        title: `OAT-METEO · ${eq.name}`,
        bas: { name: `BAS ${bas.dis || bas.name}`, data: ctx.dispSeries(sig.get(bas.uuid) || [], ctx.siUnit(bas)) },
        web: { name: `web ${web.dis || web.name}`, data: ctx.dispSeries(sig.get(web.uuid) || [], ctx.siUnit(web)) },
        unit: ctx.unit(bas), withLane: lane.length > 0,
      });
      if (!(sig.get(bas.uuid) || []).length) return "No history in this range.";
      built.option = rcxWithFaultLane(built.option, [{ name: "OAT-METEO", data: lane }]);
      draw(el, built, `fdd_OAT-METEO_${eq.name}`);
      return lane.length ? `fault in ${lane.filter(([, f]) => f).length} of ${lane.length} hourly results`
        : "no OAT-METEO result point for this equip yet (lane omitted)";
    },
  });

  // Temperature / humidity / pressure roles the SV-* rules check (all exist in fdd-catalog roles).
  const SENSOR_ROLES = ["oa_t", "mat", "zone_t", "rat", "sat", "chw_supply_t", "chw_return_t", "hw_supply_t",
    "hw_return_t", "oa_h", "ra_h", "zone_rh", "ma_h", "sa_h", "duct_static"];

  /** Bound sensor points for an equip: [{ role, p }] in SENSOR_ROLES order. */
  const sensorsOf = (ctx, eq) => SENSOR_ROLES.map((role) => ({ role, p: ctx.first(eq, role) })).filter((s) => s.p);

  const svParam = (ctx, rule, key, dflt) => {
    const r = ((ctx.catalog && ctx.catalog.rules) || []).find((x) => x.id === rule);
    const v = r && r.parameters && r.parameters[key];
    return finite(v) ? v : dflt;
  };

  rcxView({
    id: "fdd-sensor-health", group: "Sensors", title: "Sensor health by hour (stale / flatline / out of range)",
    roles: { required: [], optional: SENSOR_ROLES }, scope: "equip", hours: 168,
    async render(el, ctx) {
      const eq = ctx.equips[0];
      const sensors = sensorsOf(ctx, eq);
      if (!sensors.length) return "No temperature, humidity or pressure sensor roles are bound on this equip.";
      const pts = sensors.map((s) => s.p);
      const [avg, min, max, count] = await Promise.all(["AVERAGE", "MIN", "MAX", "COUNT"]
        .map((method) => ctx.series(pts, { windowSec: 3600, method })));
      const now = hourFloor(Date.now());
      const grid = Array.from({ length: ctx.hours }, (_, i) => now - (ctx.hours - 1 - i) * HOUR);
      const stale = svParam(ctx, "SV-STALE", "stale_hours", 2), tol = svParam(ctx, "SV-FLATLINE", "flatline_tol", 0.055556);
      const rows = sensors.map(({ role, p }) => ({
        label: `${role} · ${p.dis || p.name}`,
        states: fddPlotHealthStates(grid, { avg: hourly(avg.get(p.uuid)), min: hourly(min.get(p.uuid)),
          max: hourly(max.get(p.uuid)), count: hourly(count.get(p.uuid)) },
        { family: unitFamily(p), staleHours: stale, flatTol: tol }),
      }));
      const option = fddPlotHealthOption({ title: `Sensor health · ${eq.name}`, rows, hours: grid });
      draw(el, { option, heightPx: Math.max(220, 44 + 86 + rows.length * 26) }, `sensor_health_${eq.name}`);
      const flags = rows.flatMap((r) => r.states).filter((s) => s != null && s > 0).length;
      return `${rows.length} sensors · ${flags} flagged sensor-hours of ${rows.flatMap((r) => r.states).filter((s) => s != null).length}`;
    },
  });

  rcxView({
    id: "fdd-sensor-fault", group: "Sensors", title: "Sensor fault lanes (worst sensor)",
    roles: { required: [], optional: SENSOR_ROLES }, scope: "equip", hours: 168,
    async render(el, ctx) {
      const eq = ctx.equips[0];
      const sensors = sensorsOf(ctx, eq);
      if (!sensors.length) return "No temperature, humidity or pressure sensor roles are bound on this equip.";
      const windowSec = 3600;
      const data = await ctx.series(sensors.map((s) => s.p), { windowSec });
      let worst = null;
      for (const { role, p } of sensors) {
        const arr = data.get(p.uuid) || [];
        if (!arr.length) continue;
        const fam = unitFamily(p);
        const y = arr.map(([, v]) => v);
        // Hourly samples (SI): flatline = 3 identical hours; physical bounds are SI limits.
        const bounds = SENSOR_LIMITS[fam] || null;
        const masks = fddPlotSensorMasks(y, { flatlineWindow: 3, minSlice: 3, bounds });
        const score = Object.values(masks).reduce((a, m) => a + m.reduce((x, z) => x + z, 0), 0);
        if (!worst || score > worst.score) worst = { role, p, arr, masks, score };
      }
      if (!worst) return "No history in this range.";
      const t = worst.arr.map(([x]) => x);
      const lanes = fddPlotMaskLanes(t, worst.masks);
      const built = fddPlotSensorFaultOption({
        title: `Sensor fault lanes · ${eq.name} · ${worst.role}`, name: worst.p.dis || worst.p.name, yTitle: ctx.unit(worst.p),
        t, y: ctx.dispSeries(worst.arr, ctx.siUnit(worst.p)).map(([, v]) => v), nLanes: lanes.length,
      });
      built.option = rcxWithFaultLane(built.option, lanes);
      draw(el, built, `sensor_fault_${eq.name}_${worst.role}`);
      return `${worst.role} (${worst.p.dis || worst.p.name}): ${worst.score} flagged samples across ${Object.keys(worst.masks).length} lanes`;
    },
  });

  Object.assign(globalThis, {
    fddRulePlot, fddPlotMaskLanes, fddPlotExpandRoles, fddPlotRuleOption, fddPlotOatOption, fddPlotHealthStates,
    fddPlotHealthOption, fddPlotSensorMasks, fddPlotSensorFaultOption, fddPlotUnitFamily: unitFamily, fddPlotLimits: SENSOR_LIMITS,
  });
})();
