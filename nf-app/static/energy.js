// Units: ctx.series hands over canonical SI (kW, kWh, degC), so the meter math, degree days (C-days,
// base 18.333 C = 65 F), baselines and M&V all run in SI. Only the last step maps to the display
// system: degree days x1.8 (F-days) and EUI as kBtu/ft2/yr (imperial) or kWh/m2/yr (SI).
// Energy (fuel / EUI / M&V) views for the Open-FDD NF app, registered with rcxView().
// Port of the archived central UI's fuel-charts.js + mv-charts.js, fed only from NF:
// electric meter points (roles electric_kw / electric_kwh) + the site's outside-air temperature.
//
//   * Meter kW  (role electric_kw, power sensor)  -> kWh = average kW x window hours
//   * Meter kWh (role electric_kwh, energy register, cumulative) -> kWh = difference between
//     consecutive windows (a negative step = register reset, skipped). Each view has a "(kWh register)"
//     twin; the twin steps aside when the same meter already binds a kW point.
//   * Degree days: base 18.333 °C (65 °F), daily mean of the site outside-air temperature (equip oa_t,
//     else the site's weather points); HDD = max(0, base - T), CDD = max(0, T - base), in °C-days.
//   * Baseline (weather normalisation): daily kWh vs CDD or HDD, least squares (rcxStats.fit), the
//     degree-day kind with the better r2 whose slope >= 0. Complete days only (>= 80 % coverage).
//   * M&V: fit on a chosen baseline period, predict the reporting period from its degree days,
//     savings = sum(predicted - actual); CV(RMSE) = sqrt(sum(res^2) / (n - 2)) / mean(actual).
//   * EUI = kWh / floor area (m2) x 365 / days covered (kWh/m2/yr), shown as kBtu/ft2/yr in the
//     imperial display system. Floor area = the NF site record's `area` attribute, assumed ft2 unless
//     the site has `areaUnit` "m²". Without it, charts show kWh (per day for site comparisons).
//   * Site comparison views need >= 2 modeled sites with a meter; a site's energy = its largest
//     meter (submeters are assumed to be subsets), so nothing is double counted.
// Utility bills and fuel prices are not in NF, so bill-based charts are not ported.
// No import/export, nothing eval-like: strict CSP. Needs rcx.js, fdd.js, model.js, theme.js, charts.js.
(() => {
  "use strict";

  const TEMP = "°C";
  const BASE_C = (65 - 32) * 5 / 9;          // degree-day base: 65 F = 18.333 C
  const KBTU_PER_KWH = 3.412;
  const FT2_PER_M2 = 10.7639104;
  const COMPLETE = 0.8;
  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  const finite = (x) => x != null && typeof x === "number" && Number.isFinite(x);
  const pad = (n) => String(n).padStart(2, "0");
  const dayKey = (ms) => { const d = new Date(ms); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const monthKey = (ms) => dayKey(ms).slice(0, 7);
  const dayStart = (k) => new Date(+k.slice(0, 4), +k.slice(5, 7) - 1, +k.slice(8, 10)).getTime();
  const monthStart = (k) => new Date(+k.slice(0, 4), +k.slice(5, 7) - 1, 1).getTime();
  const sum = (xs) => xs.reduce((a, b) => a + b, 0);
  const mean = (xs) => { const v = xs.filter(finite); return v.length ? sum(v) / v.length : null; };
  const quantile = (xs, q) => {
    const v = xs.filter(finite).sort((a, b) => a - b);
    if (!v.length) return null;
    const i = (v.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
    return v[lo] + (v[hi] - v[lo]) * (i - lo);
  };

  // ---- pure math ---------------------------------------------------------------------
  /** Hourly windows up to ~400 days of history, daily beyond. */
  const pickEnergyWindow = (hours) => (hours <= 9600 ? 3600 : 86400);

  /** Cumulative register [[t, v]] -> per-step deltas [[t, d]]; the first sample and resets (d < 0) are skipped. */
  function cumulativeDeltas(pairs) {
    const out = [];
    for (let i = 1; i < pairs.length; i++) {
      const d = pairs[i][1] - pairs[i - 1][1];
      if (finite(d) && d >= 0) out.push([pairs[i][0], d]);
    }
    return out;
  }

  /** [[t, kWh]] per window (pairs in SI: kW or kWh). source "kw": average kW x window hours; "kwh": register deltas. */
  function intervalKwh(pairs, source, windowSec) {
    if (source === "kwh") return cumulativeDeltas(pairs);
    return pairs.filter(([, v]) => finite(v)).map(([t, v]) => [t, v * windowSec / 3600]);
  }

  /** [[t, kW]] per window (register deltas become average kW). */
  function intervalKw(pairs, source, windowSec) {
    if (source === "kwh") return cumulativeDeltas(pairs).map(([t, d]) => [t, d * 3600 / windowSec]);
    return pairs.filter(([, v]) => finite(v)).map(([t, v]) => [t, v]);
  }

  /** Degree days in C-days from a daily mean temperature in degC. */
  const degreeDays = (tC, base = BASE_C) => (finite(tC) ? { hdd: Math.max(0, base - tC), cdd: Math.max(0, tC - base) } : { hdd: null, cdd: null });

  /**
   * One row per local day: { day, t, kwh, peakKw, hours, meanT, hdd, cdd, complete }.
   * kwhPairs/kwPairs/oatPairs are [[ms, v]] (kWh, kW, oat in degC); windowSec is their step.
   * hdd/cdd are C-days.
   */
  function dailyTable(kwhPairs, kwPairs, oatPairs, windowSec, base = BASE_C) {
    const days = new Map();
    const row = (k) => { if (!days.has(k)) days.set(k, { kwh: 0, n: 0, peak: null, temps: [] }); return days.get(k); };
    for (const [t, v] of kwhPairs) { const r = row(dayKey(t)); r.kwh += v; r.n++; }
    for (const [t, v] of kwPairs) { const r = row(dayKey(t)); r.peak = r.peak == null ? v : Math.max(r.peak, v); }
    for (const [t, v] of oatPairs || []) if (finite(v) && days.has(dayKey(t))) days.get(dayKey(t)).temps.push(v);
    return [...days.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).filter(([, r]) => r.n > 0).map(([day, r]) => {
      const meanT = mean(r.temps);
      const hours = r.n * windowSec / 3600;
      return { day, t: dayStart(day), kwh: r.kwh, peakKw: r.peak, hours, meanT, ...degreeDays(meanT, base), complete: hours >= 24 * COMPLETE };
    });
  }

  /** Daily rows -> one row per month: { month, t, kwh, peakKw, days, hdd, cdd }. */
  function monthlyTable(daily) {
    const m = new Map();
    for (const d of daily) {
      const k = d.day.slice(0, 7);
      if (!m.has(k)) m.set(k, { month: k, t: monthStart(k), kwh: 0, peakKw: null, days: 0, hdd: 0, cdd: 0 });
      const r = m.get(k);
      r.kwh += d.kwh; r.days += d.hours / 24;
      if (finite(d.peakKw)) r.peakKw = r.peakKw == null ? d.peakKw : Math.max(r.peakKw, d.peakKw);
      if (finite(d.hdd)) r.hdd += d.hdd;
      if (finite(d.cdd)) r.cdd += d.cdd;
    }
    return [...m.values()].sort((a, b) => (a.month < b.month ? -1 : 1));
  }

  const fitPairs = (pairs) => (typeof rcxStats !== "undefined" ? rcxStats.fit(pairs) : null);

  /** Baseline kWh/day = a + b x (degree days). xKey "cdd" | "hdd"; omitted = better r2 with slope >= 0. */
  function baselineFit(rows, xKey) {
    const ok = rows.filter((r) => r.complete !== false && finite(r.kwh));
    const tryKey = (k) => {
      const pairs = ok.filter((r) => finite(r[k])).map((r) => [r[k], r.kwh]);
      if (pairs.length < 2) return null;
      const f = fitPairs(pairs);
      // No degree-day variation (e.g. no cooling days): a flat baseline at the mean.
      if (!f) return { xKey: k, slope: 0, intercept: mean(pairs.map((p) => p[1])), r2: 0, n: pairs.length };
      return { xKey: k, ...f, n: pairs.length };
    };
    if (xKey) return tryKey(xKey);
    const cands = ["cdd", "hdd"].map(tryKey).filter(Boolean);
    if (!cands.length) return null;
    const good = cands.filter((c) => c.slope >= 0);
    return (good.length ? good : cands).sort((a, b) => b.r2 - a.r2)[0];
  }

  const predict = (fit, x) => Math.max(0, fit.intercept + fit.slope * x);

  /** Actual vs baseline per day: [{ day, x, actual, predicted, residual }]. */
  function residuals(rows, fit) {
    return rows.filter((r) => r.complete !== false && finite(r[fit.xKey])).map((r) => {
      const predicted = predict(fit, r[fit.xKey]);
      return { day: r.day, x: r[fit.xKey], actual: r.kwh, predicted, residual: r.kwh - predicted };
    });
  }

  /**
   * M&V: fit on baseline days, predict reporting days.
   * baseline/reporting = { from: "YYYY-MM-DD", to: "YYYY-MM-DD" } (inclusive, local days).
   * savings = sum(predicted - actual) over the reporting days (positive = less energy than the baseline predicts).
   */
  function mvSavings(rows, baseline, reporting, xKey) {
    const inR = (r, p) => r.complete !== false && r.day >= p.from && r.day <= p.to && finite(r.kwh);
    const base = rows.filter((r) => inR(r, baseline));
    const rep = rows.filter((r) => inR(r, reporting));
    if (base.length < 3 || !rep.length) return null;
    const fit = baselineFit(base, xKey);
    if (!fit) return null;
    const repRes = residuals(rep, fit);
    const baseRes = residuals(base, fit);
    if (!repRes.length) return null;
    const actual = sum(repRes.map((r) => r.actual)), predicted = sum(repRes.map((r) => r.predicted));
    const my = mean(baseRes.map((r) => r.actual));
    const dof = Math.max(1, baseRes.length - 2);
    const cvrmse = my ? Math.sqrt(sum(baseRes.map((r) => r.residual ** 2)) / dof) / my : null;
    const nmbe = my ? sum(baseRes.map((r) => r.residual)) / (dof * my) : null;
    return {
      fit, baseDays: baseRes.length, repDays: repRes.length, actual, predicted,
      savings: predicted - actual, pct: predicted ? (predicted - actual) / predicted : null, cvrmse, nmbe,
      baseline: baseRes, reporting: repRes,
    };
  }

  /** EUI in kWh/m2/yr (SI) from kWh over `days` days and a floor area in m2; null without a positive area. */
  const eui = (kwh, days, areaM2) => (areaM2 > 0 && days > 0 ? (kwh / areaM2) * (365 / days) : null);
  /** EUI (kWh/m2/yr) -> display value: kBtu/ft2/yr (imperial) or unchanged (si). */
  const euiDisp = (v, system) => (!finite(v) ? null : system === "imperial" ? v * KBTU_PER_KWH / FT2_PER_M2 : v);
  const euiUnit = (system) => (system === "imperial" ? "kBtu/ft²/yr" : "kWh/m²/yr");
  /** Display options for degree days: ddK x C-days, label unit and base in the display system. */
  const ddDisplay = (k = 1) => (k === 1 ? { k, unit: "°C·day", base: +BASE_C.toFixed(1) } : { k, unit: "°F·day", base: Math.round(BASE_C * k + 32) });

  /** Trailing up-to-12-month totals: [{ month, kwh, days }]. */
  function rolling12(monthly) {
    return monthly.map((m, i) => {
      const w = monthly.slice(Math.max(0, i - 11), i + 1);
      return { month: m.month, kwh: sum(w.map((x) => x.kwh)), days: sum(w.map((x) => x.days)) };
    });
  }

  /** Mean kW by hour of day x weekday: { data: [[hour, dow, kW]], max }. */
  function heatmapGrid(kwPairs) {
    const acc = new Map();
    for (const [t, v] of kwPairs) {
      const d = new Date(t), k = `${d.getHours()}|${d.getDay()}`;
      const a = acc.get(k) || [0, 0];
      a[0] += v; a[1]++;
      acc.set(k, a);
    }
    const data = [...acc.entries()].map(([k, [s, n]]) => { const [h, w] = k.split("|").map(Number); return [h, w, s / n]; });
    return { data, max: Math.max(1, ...data.map((d) => d[2])) };
  }

  /** Cooling days (CDD > 0) vs the rest: peak and mean daily peak kW. */
  function seasonPeaks(daily) {
    const part = (name, rows) => ({
      season: name, days: rows.length,
      peakKw: rows.length ? Math.max(...rows.map((r) => r.peakKw ?? 0)) : null,
      meanPeakKw: mean(rows.map((r) => r.peakKw)),
    });
    const withT = daily.filter((r) => finite(r.cdd) && finite(r.peakKw));
    return [part("Cooling days", withT.filter((r) => r.cdd > 0)), part("Other days", withT.filter((r) => !(r.cdd > 0)))].filter((s) => s.days);
  }

  // ---- chart options (theme-free) -------------------------------------------------------
  const num1 = (v) => (finite(v) ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)) : "–");
  const baseGrid = { left: 58, right: 24, top: 40, bottom: 44 };

  function demandHeatmapOption(grid) {
    return {
      grid: { left: 58, right: 24, top: 16, bottom: 70 },
      tooltip: { trigger: "item", formatter: (p) => `${DOW[p.value[1]]} ${pad(p.value[0])}:00 – ${num1(p.value[2])} kW` },
      xAxis: { type: "category", data: Array.from({ length: 24 }, (_, h) => pad(h)), name: "hour", splitArea: { show: true } },
      yAxis: { type: "category", data: DOW, inverse: true },
      visualMap: { min: 0, max: grid.max, calculable: true, orient: "horizontal", left: "center", bottom: 4, text: ["kW", ""] },
      series: [{ type: "heatmap", data: grid.data }],
      dataZoom: false,
    };
  }

  function intervalDemandOption(kwPairs) {
    return {
      grid: { ...baseGrid },
      tooltip: { trigger: "axis", suffix: " kW" },
      xAxis: { type: "time" },
      yAxis: { type: "value", name: "kW", scale: true },
      series: [{ name: "Demand", type: "line", showSymbol: false, data: kwPairs, lineStyle: { width: 1.4 } }],
    };
  }

  function monthlyLinesOption(monthly, unit = "kWh") {
    return {
      grid: { ...baseGrid },
      legend: { top: 0 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "time" },
      yAxis: { type: "value", name: unit, scale: true },
      series: [{ name: `Monthly ${unit}`, type: "line", symbolSize: 7, data: monthly.map((m) => [m.t, m.kwh]) }],
    };
  }

  // rows/fit/res are SI (C-days); `dd` (ddDisplay) only maps the degree-day axis to display units.
  function weatherOption(rows, fit, res, dd = ddDisplay()) {
    const xs = rows.filter((r) => r.complete && finite(r[fit.xKey])).map((r) => r[fit.xKey]);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    const label = fit.xKey.toUpperCase();
    return {
      grid: [{ left: 56, right: "56%", top: 44, bottom: 40 }, { left: "52%", right: 24, top: 44, bottom: 40 }],
      legend: { top: 0 },
      tooltip: { trigger: "item", formatter: (p) => (Array.isArray(p.value) ? `${label} ${num1(p.value[0])}: ${num1(p.value[1])}` : `${p.name}: ${num1(p.value)}`) },
      xAxis: [{ type: "value", gridIndex: 0, name: `${label} (${dd.unit}, base ${dd.base})`, nameLocation: "middle", nameGap: 26, scale: true },
        { type: "category", gridIndex: 1, data: res.map((r) => r.day.slice(5)), axisLabel: { hideOverlap: true } }],
      yAxis: [{ type: "value", gridIndex: 0, name: "kWh/day", scale: true }, { type: "value", gridIndex: 1, name: "actual − baseline kWh", scale: true }],
      series: [
        { name: "Days", type: "scatter", xAxisIndex: 0, yAxisIndex: 0, symbolSize: 8, data: res.map((r) => [r.x * dd.k, r.actual]) },
        { name: `Baseline (r² ${fit.r2.toFixed(2)})`, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false,
          data: [[lo * dd.k, predict(fit, lo)], [hi * dd.k, predict(fit, hi)]] },
        { name: "Residual", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: res.map((r) => r.residual) },
      ],
      dataZoom: false,
    };
  }

  function peakDualOption(monthly) {
    return {
      grid: { ...baseGrid, right: 56 },
      legend: { top: 0 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: monthly.map((m) => m.month) },
      yAxis: [{ type: "value", name: "kW" }, { type: "value", name: "kWh", position: "right", splitLine: { show: false } }],
      series: [
        { name: "Peak kW", type: "bar", data: monthly.map((m) => m.peakKw) },
        { name: "kWh", type: "line", yAxisIndex: 1, showSymbol: true, data: monthly.map((m) => m.kwh) },
      ],
    };
  }

  function peakSeasonOption(seasons) {
    return {
      grid: { ...baseGrid },
      legend: { top: 0 },
      tooltip: { trigger: "axis", suffix: " kW" },
      xAxis: { type: "category", data: seasons.map((s) => `${s.season} (${s.days} d)`) },
      yAxis: { type: "value", name: "kW" },
      series: [{ name: "Peak kW", type: "bar", data: seasons.map((s) => s.peakKw) },
        { name: "Mean daily peak kW", type: "bar", data: seasons.map((s) => s.meanPeakKw) }],
      dataZoom: false,
    };
  }

  function mvOption(res, dd = ddDisplay()) {
    const label = res.fit.xKey.toUpperCase();
    const xs = [...res.baseline, ...res.reporting].map((r) => r.x);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    return {
      grid: { ...baseGrid, left: 62 },
      legend: { top: 0 },
      tooltip: { trigger: "item", formatter: (p) => `${p.seriesName}: ${label} ${num1(p.value[0])} → ${num1(p.value[1])} kWh` },
      xAxis: { type: "value", name: `${label} (${dd.unit}, base ${dd.base})`, nameLocation: "middle", nameGap: 26, scale: true },
      yAxis: { type: "value", name: "kWh/day", scale: true },
      series: [
        { name: "Baseline", type: "scatter", symbolSize: 8, data: res.baseline.map((r) => [r.x * dd.k, r.actual]) },
        { name: "Reporting", type: "scatter", symbolSize: 8, data: res.reporting.map((r) => [r.x * dd.k, r.actual]) },
        { name: "Baseline model", type: "line", showSymbol: false, data: [[lo * dd.k, predict(res.fit, lo)], [hi * dd.k, predict(res.fit, hi)]] },
        { name: "Predicted (reporting)", type: "scatter", symbol: "diamond", symbolSize: 8, data: res.reporting.map((r) => [r.x * dd.k, r.predicted]) },
      ],
      dataZoom: false,
    };
  }

  // Site comparison charts -----------------------------------------------------------------
  /** Per-site value + axis label: EUI (display system) when every site has an area (m2), else kWh/day. */
  function siteMetric(sites, system = "si") {
    const allArea = sites.length > 0 && sites.every((s) => s.area > 0);
    const value = (kwh, days, areaM2) => (allArea ? euiDisp(eui(kwh, days, areaM2), system) : days > 0 ? kwh / days : null);
    return { allArea, value, label: allArea ? `${euiUnit(system)} (annualized)` : "kWh/day" };
  }

  const sortedBars = (rows) => [...rows].sort((a, b) => b.value - a.value);

  function peerBarsOption(rows, metric, title = "") {
    const med = quantile(rows.map((r) => r.value), 0.5);
    return {
      grid: { ...baseGrid, bottom: 60 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: rows.map((r) => r.name), axisLabel: { hideOverlap: true } },
      yAxis: { type: "value", name: metric.label, nameLocation: "end" },
      series: [{ name: title || "Sites", type: "bar", data: rows.map((r) => r.value),
        markLine: { symbol: "none", data: [{ yAxis: med, name: "median", label: { formatter: `median ${num1(med)}` } }] } }],
      dataZoom: false,
    };
  }

  function peerBulletOption(row, rows, metric) {
    const vals = rows.map((r) => r.value);
    const med = quantile(vals, 0.5), p90 = quantile(vals, 0.9);
    return {
      grid: { left: 90, right: 40, top: 30, bottom: 36 },
      tooltip: { trigger: "item", formatter: (p) => `${row.name}: ${num1(row.value)} ${metric.label}` },
      xAxis: { type: "value", name: metric.label, min: 0, max: Math.max(p90, row.value) * 1.15 },
      yAxis: { type: "category", data: [row.name] },
      series: [{ type: "bar", name: row.name, barWidth: 22, data: [row.value],
        markLine: { symbol: "none", data: [{ xAxis: med, label: { formatter: `peer median ${num1(med)}` } }, { xAxis: p90, label: { formatter: `peer p90 ${num1(p90)}` } }] } }],
      dataZoom: false,
    };
  }

  function rankedOption(rows, metric) {
    const s = sortedBars(rows);
    return {
      grid: { left: 110, right: 32, top: 24, bottom: 36 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "value", name: metric.label },
      yAxis: { type: "category", data: s.map((r) => r.name), inverse: true },
      series: [{ name: metric.label, type: "bar", data: s.map((r) => r.value) }],
      dataZoom: false,
    };
  }

  function rollingOption(sites, metric) {
    const months = [...new Set(sites.flatMap((s) => s.rolling.map((r) => r.month)))].sort();
    return {
      grid: { ...baseGrid },
      legend: { top: 0 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: months },
      yAxis: { type: "value", name: metric.label, scale: true },
      series: sites.map((s) => ({
        name: s.name, type: "line", showSymbol: true, connectNulls: false,
        data: months.map((m) => { const r = s.rolling.find((x) => x.month === m); return r ? metric.value(r.kwh, r.days, s.area) : null; }),
      })),
    };
  }

  function intensityOption(sites, metric) {
    const months = [...new Set(sites.flatMap((s) => s.monthly.map((m) => m.month)))].sort();
    const data = [];
    sites.forEach((s, yi) => months.forEach((mo, xi) => {
      const m = s.monthly.find((x) => x.month === mo);
      const v = m ? metric.value(m.kwh, m.days, s.area) : null;
      if (finite(v)) data.push([xi, yi, v]);
    }));
    return {
      grid: { left: 110, top: 16, right: 32, bottom: 70 },
      tooltip: { trigger: "item", formatter: (p) => `${sites[p.value[1]].name} ${months[p.value[0]]}: ${num1(p.value[2])} ${metric.label}` },
      xAxis: { type: "category", data: months, splitArea: { show: true } },
      yAxis: { type: "category", data: sites.map((s) => s.name) },
      visualMap: { min: 0, max: Math.max(1, ...data.map((d) => d[2])), calculable: true, orient: "horizontal", left: "center", bottom: 4 },
      series: [{ type: "heatmap", data }],
      dataZoom: false,
    };
  }

  function stackedOption(meters) {
    const months = [...new Set(meters.flatMap((m) => m.monthly.map((x) => x.month)))].sort();
    return {
      grid: { ...baseGrid },
      legend: { top: 0 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: months },
      yAxis: { type: "value", name: "kWh" },
      series: meters.map((m) => ({
        name: m.name, type: "bar", stack: "energy",
        data: months.map((mo) => { const r = m.monthly.find((x) => x.month === mo); return r ? r.kwh : null; }),
      })),
    };
  }

  globalThis.energyMath = {
    BASE_C, KBTU_PER_KWH, FT2_PER_M2, pickEnergyWindow, cumulativeDeltas, intervalKwh, intervalKw,
    degreeDays, dailyTable, monthlyTable, baselineFit, predict, residuals, mvSavings, eui, euiDisp, euiUnit, ddDisplay, rolling12,
    heatmapGrid, seasonPeaks, siteMetric, dayKey, monthKey,
    charts: { demandHeatmapOption, intervalDemandOption, monthlyLinesOption, weatherOption, peakDualOption, peakSeasonOption,
      mvOption, peerBarsOption, peerBulletOption, rankedOption, rollingOption, intensityOption, stackedOption },
  };

  // ---- NF data loading --------------------------------------------------------------------
  const outsideAirPoint = (ctx, siteRef) => {
    const pool = ctx.model.points.filter((p) => has(p, "point") && p.siteRef === siteRef);
    const b = bindRoles(["oa_t", "web_oa_t"], pool, ctx.catalog);
    return b.oa_t[0] || b.web_oa_t[0] || null;
  };

  const meterPoint = (ctx, eq) => {
    const kw = ctx.first(eq, "electric_kw");
    if (kw) return { pt: kw, source: "kw" };
    const kwh = ctx.first(eq, "electric_kwh") || ctx.first(eq, "kwh");
    return kwh ? { pt: kwh, source: "kwh" } : null;
  };

  /** Interval + daily + monthly energy for one meter point and its site's outside air. */
  async function loadMeter(ctx, pt, source, siteRef) {
    const windowSec = pickEnergyWindow(ctx.hours);
    const opts = { hours: ctx.hours, windowSec };
    const oatPt = outsideAirPoint(ctx, siteRef);
    const [m, o] = await Promise.all([
      ctx.series([pt], { ...opts, method: source === "kw" ? "AVERAGE" : "MAX" }),
      oatPt ? ctx.series([oatPt], { ...opts, method: "AVERAGE" }) : Promise.resolve(null),
    ]);
    const raw = m.get(pt.uuid) || [];
    // ctx.series already converted W/MW/Btu/h -> kW, Wh/kBtu/therm -> kWh and F/K -> degC
    const kwh = intervalKwh(raw, source, windowSec);
    const kw = intervalKw(raw, source, windowSec);
    const oat = oatPt ? (o.get(oatPt.uuid) || []) : [];
    const daily = dailyTable(kwh, kw, oat, windowSec);
    return { pt, source, windowSec, kwh, kw, oat, oatPt, daily, monthly: monthlyTable(daily), total: sum(kwh.map((x) => x[1])) };
  }

  const siteRecord = (model, siteRef) => model.sites.find((s) => idOf(s) === siteRef) || null;
  /** Site floor area in m2: the NF `area` attribute is ft2 unless the site has `areaUnit` m2. */
  const siteArea = (model, siteRef) => {
    const s = siteRecord(model, siteRef);
    const a = s ? parseFloat((s.attrs || {}).area) : NaN;
    if (!(a > 0)) return null;
    const u = String((s.attrs || {}).areaUnit || "").toLowerCase().replace(/[\s²]/g, "").replace("2", "");
    return u === "m" || u === "sqm" ? a : a / FT2_PER_M2;
  };
  const areaNote = (ctx, siteRef, monthly) => {
    const area = siteArea(ctx.model, siteRef);
    if (!area) return "No floor area (`area`) on the NF site record, so kWh is shown, not EUI.";
    const days = sum(monthly.map((m) => m.days));
    const sys = ctx.dispSystem();
    const v = euiDisp(eui(sum(monthly.map((m) => m.kwh)), days, area), sys);
    const areaTxt = sys === "imperial" ? `${num1(area * FT2_PER_M2)} ft²` : `${num1(area)} m²`;
    return v == null ? "" : `EUI ${num1(v)} ${euiUnit(sys)} (annualized from ${num1(days)} days, area ${areaTxt}).`;
  };
  globalThis.energyMath.siteArea = siteArea;   // pure; exposed for tests
  /** Degree-day display options for the current display system. */
  const ddOf = (ctx) => ddDisplay(ctx.dispDelta(1, TEMP).value);

  const noteNoData = (ctx, pt) => `No history for ${pt.dis} in the last ${ctx.hours} h.`;
  const noWeather = "No outside-air temperature (equip oa_t or site weather point) for degree days.";

  const siteRefOf = (eq) => (eq.rec.attrs || {}).siteRef;
  const draw = (ctx, el, option, name) => ofddRender(ctx.chart(el), { animationDuration: 300, ...option }, name);

  // ---- equip views (one card per meter) -----------------------------------------------------
  /** Registers `id` on electric_kw and `id`-kwh on electric_kwh. build(ctx, el, eq, data) -> note | undefined. */
  function equipView(id, title, build, extra = {}) {
    for (const source of ["kw", "kwh"]) {
      rcxView({
        id: source === "kw" ? id : `${id}-kwh`,
        group: "Energy",
        title: source === "kw" ? title : `${title} (kWh register)`,
        kinds: ["meter"],
        // The kWh twin also lists electric_kw so it can see (and defer to) the meter's kW view.
        roles: { required: [source === "kw" ? "electric_kw" : "electric_kwh"], optional: source === "kw" ? [] : ["electric_kw"] },
        scope: "equip", hours: 720, ...extra,
        render: async (el, ctx) => {
          const eq = ctx.equips[0];
          if (source === "kwh" && ctx.first(eq, "electric_kw")) { el.textContent = "Shown by the kW view of this meter."; return "Covered by the kW view."; }
          const pt = source === "kw" ? ctx.first(eq, "electric_kw") : ctx.first(eq, "electric_kwh");
          const data = await loadMeter(ctx, pt, source, siteRefOf(eq));
          if (!data.kwh.length) { el.textContent = noteNoData(ctx, pt); return noteNoData(ctx, pt); }
          return build(ctx, el, eq, data);
        },
      });
    }
  }

  equipView("energy-demand-heatmap", "Interval demand heatmap (hour × weekday)", (ctx, el, eq, d) => {
    draw(ctx, el, demandHeatmapOption(heatmapGrid(d.kw)), "demand-heatmap");
    return `Mean kW per hour of day and weekday, ${ctx.hours} h of ${d.windowSec / 60}-minute values.`;
  });

  equipView("energy-interval-demand", "Interval demand (kW)", async (ctx, el, eq, d) => {
    const lane = await rcxFaultData(ctx.model, eq.id, "UTIL-INTERVAL", ctx.hours);
    draw(ctx, el, rcxWithFaultLane(intervalDemandOption(d.kw), [{ name: "UTIL-INTERVAL", data: lane }]), "interval-demand");
    return lane.length ? "Fault lane: UTIL-INTERVAL." : "";
  });

  equipView("energy-monthly", "Monthly energy (kWh)", async (ctx, el, eq, d) => {
    const lane = await rcxFaultData(ctx.model, eq.id, "UTIL-MONTHLY", ctx.hours);
    draw(ctx, el, rcxWithFaultLane(monthlyLinesOption(d.monthly), [{ name: "UTIL-MONTHLY", data: lane }]), "monthly-energy");
    return `${areaNote(ctx, siteRefOf(eq), d.monthly)} Edge months may be partial; history is limited to ${ctx.hours} h.`;
  }, { hours: 2160 });

  equipView("energy-weather-scatter", "Energy vs degree days + residuals", (ctx, el, eq, d) => {
    if (!d.oat.length) { el.textContent = noWeather; return noWeather; }
    const fit = baselineFit(d.daily);
    if (!fit) { el.textContent = "Need at least 2 complete days with outside-air data."; return "Need at least 2 complete days."; }
    const dd = ddOf(ctx);
    draw(ctx, el, weatherOption(d.daily, fit, residuals(d.daily, fit), dd), "energy-weather");
    return `Daily kWh = ${num1(fit.intercept)} + ${(fit.slope / dd.k).toFixed(2)} × ${fit.xKey.toUpperCase()} (${dd.unit}, base ${dd.base}), r² ${fit.r2.toFixed(2)}, ${fit.n} days.`;
  });

  equipView("energy-demand-peak", "Monthly peak kW vs kWh", (ctx, el, eq, d) => {
    if (!d.monthly.some((m) => finite(m.peakKw))) { el.textContent = "No demand values."; return "No demand values."; }
    draw(ctx, el, peakDualOption(d.monthly), "demand-peak");
  }, { hours: 2160 });

  equipView("energy-peak-cooling", "Peak demand: cooling days vs other days", (ctx, el, eq, d) => {
    if (!d.oat.length) { el.textContent = noWeather; return noWeather; }
    const seasons = seasonPeaks(d.daily);
    if (!seasons.length) { el.textContent = "No days with both demand and outside air."; return "No usable days."; }
    draw(ctx, el, peakSeasonOption(seasons), "peak-vs-cooling");
    return `Cooling day = daily mean outside air above ${ddOf(ctx).base} ${ctx.dispUnit(TEMP)}.`;
  });

  equipView("energy-mv", "M&V: baseline vs reporting period", async (ctx, el, eq, d) => {
    if (!d.oat.length) { el.textContent = noWeather; return noWeather; }
    const days = d.daily.filter((r) => r.complete && finite(r.cdd));
    if (days.length < 6) { el.textContent = "Need at least 6 complete days with outside air for M&V."; return "Need at least 6 complete days."; }
    const host = el.parentNode;
    for (const old of host.querySelectorAll(".mv-controls, .mv-summary")) old.remove();
    const split = Math.ceil(days.length / 2);
    const defaults = { bf: days[0].day, bt: days[split - 1].day, rf: days[split].day, rt: days[days.length - 1].day };
    const bar = document.createElement("div");
    bar.className = "mv-controls sub";
    const inputs = {};
    for (const [key, label] of [["bf", "Baseline from"], ["bt", "to"], ["rf", "Reporting from"], ["rt", "to"]]) {
      const l = document.createElement("label");
      l.textContent = `${label} `;
      const i = document.createElement("input");
      i.type = "date"; i.value = defaults[key]; i.min = days[0].day; i.max = days[days.length - 1].day;
      l.appendChild(i); bar.appendChild(l); bar.appendChild(document.createTextNode(" "));
      inputs[key] = i;
    }
    const summary = document.createElement("div");
    summary.className = "mv-summary sub";
    host.insertBefore(bar, el);
    el.after(summary);
    const redraw = () => {
      const res = mvSavings(d.daily, { from: inputs.bf.value, to: inputs.bt.value }, { from: inputs.rf.value, to: inputs.rt.value });
      if (!res) { summary.textContent = "Baseline needs >= 3 complete days and the reporting period at least 1."; return; }
      draw(ctx, el, mvOption(res, ddOf(ctx)), "mv");
      summary.textContent = `Baseline ${res.baseDays} d (r² ${res.fit.r2.toFixed(2)}, CV(RMSE) ${res.cvrmse == null ? "–" : (res.cvrmse * 100).toFixed(1) + " %"}); `
        + `reporting ${res.repDays} d: actual ${num1(res.actual)} kWh vs predicted ${num1(res.predicted)} kWh → `
        + `${res.savings >= 0 ? "savings" : "increase"} ${num1(Math.abs(res.savings))} kWh${res.pct == null ? "" : ` (${(res.pct * 100).toFixed(1)} %)`}.`;
    };
    for (const i of Object.values(inputs)) i.onchange = redraw;
    redraw();
    return `Pick baseline and reporting days; degree days base ${ddOf(ctx).base} ${ctx.dispUnit(TEMP)} from the site outside air.`;
  }, { hours: 2160 });

  // ---- site views (all modeled sites) --------------------------------------------------------
  const siteCache = new Map();
  /** One entry per modeled site that has a meter with history: the largest meter wins. */
  async function loadSites(ctx) {
    const key = `${ctx.hours}`;
    const hit = siteCache.get(key);
    if (hit && hit.model === ctx.model && Date.now() - hit.at < 60e3) return hit.promise;
    const promise = (async () => {
      const out = [];
      for (const site of ctx.model.sites) {
        const id = idOf(site);
        const cands = [];
        for (const rec of ctx.model.equips) {
          if (siteRefOf({ rec }) !== id || !equipKinds(rec, ctx.catalog).includes("meter")) continue;
          const bound = bindRoles(["electric_kw", "electric_kwh"], equipPool(rec, ctx.model), ctx.catalog);
          const eq = { rec, bound, id: idOf(rec), name: (rec.attrs || {}).dis || rec.name };
          const m = meterPoint(ctx, eq);
          if (m) cands.push({ eq, ...m });
        }
        const loaded = await Promise.all(cands.map(async (c) => ({ c, d: await loadMeter(ctx, c.pt, c.source, id) })));
        const best = loaded.filter((x) => x.d.kwh.length).sort((a, b) => b.d.total - a.d.total)[0];
        if (!best) continue;
        const { d } = best;
        out.push({
          id, name: (site.attrs || {}).dis || site.name, area: siteArea(ctx.model, id), meter: best.c.eq.name,
          monthly: d.monthly, rolling: rolling12(d.monthly), kwh: sum(d.monthly.map((m) => m.kwh)), days: sum(d.monthly.map((m) => m.days)),
        });
      }
      return out;
    })();
    siteCache.set(key, { model: ctx.model, at: Date.now(), promise });
    promise.catch(() => siteCache.delete(key));
    return promise;
  }

  function siteView(id, title, build) {
    rcxView({
      id, group: "Energy", title, kinds: ["meter"], roles: { required: [], optional: ["electric_kw", "electric_kwh"] },
      scope: "site", hours: 2160,
      render: async (el, ctx) => {
        const sites = await loadSites(ctx);
        const card = el.closest && el.closest(".rcx-card");
        if (sites.length < 2) {
          el.textContent = "Needs at least 2 modeled sites with a meter.";
          if (card) card.hidden = true;
          return "Needs at least 2 modeled sites with a meter.";
        }
        const metric = siteMetric(sites, ctx.dispSystem());
        const rows = sites.map((s) => ({ ...s, value: metric.value(s.kwh, s.days, s.area) })).filter((r) => finite(r.value));
        if (rows.length < 2) { el.textContent = "Not enough data."; return "Not enough data."; }
        const note = await build(ctx, el, { sites, rows, metric });
        return `${metric.allArea ? "EUI uses each site's NF `area` attribute." : "A site has no `area`, so kWh/day is shown instead of EUI."} ${note || ""}`.trim();
      },
    });
  }

  siteView("energy-peer-bullet", "Site EUI vs peer median / p90", (ctx, el, { rows, metric }) => {
    const mine = (ctx.equips[0] && siteRefOf(ctx.equips[0])) || rows[0].id;
    const row = rows.find((r) => r.id === mine) || rows[0];
    draw(ctx, el, peerBulletOption(row, rows, metric), "peer-bullet");
    return `Peers = all modeled sites (${rows.length}).`;
  });
  siteView("energy-peer-bars", "Peer comparison (EUI by site)", (ctx, el, { rows, metric }) => {
    draw(ctx, el, peerBarsOption(rows, metric, "Sites"), "peer-bars");
  });
  siteView("energy-ranked-eui", "Ranked site EUI", (ctx, el, { rows, metric }) => {
    draw(ctx, el, rankedOption(rows, metric), "ranked-eui");
  });
  siteView("energy-rolling12", "Rolling 12-month EUI", (ctx, el, { sites, metric }) => {
    draw(ctx, el, rollingOption(sites, metric), "rolling12");
    return "Trailing up to 12 months, annualized from the days covered (NF history may be shorter than a year).";
  });
  siteView("energy-intensity-heatmap", "Intensity heatmap (site × month)", (ctx, el, { sites, metric }) => {
    draw(ctx, el, intensityOption(sites, metric), "intensity-heatmap");
  });

  // Stacked energy by meter on the scoped equips (electric only: the catalog has no gas role).
  rcxView({
    id: "energy-stacked-meters", group: "Energy", title: "Stacked monthly energy by meter", kinds: ["meter"],
    roles: { required: [], optional: ["electric_kw", "electric_kwh"] }, scope: "site", hours: 2160,
    render: async (el, ctx) => {
      const meters = [];
      for (const eq of ctx.equips) {
        const m = meterPoint(ctx, eq);
        if (!m) continue;
        const d = await loadMeter(ctx, m.pt, m.source, siteRefOf(eq));
        if (d.kwh.length) meters.push({ name: eq.name, monthly: d.monthly });
      }
      if (meters.length < 2) {
        el.textContent = "Needs at least 2 meters with history in scope.";
        const card = el.closest && el.closest(".rcx-card");
        if (card) card.hidden = true;
        return "Needs at least 2 meters.";
      }
      draw(ctx, el, stackedOption(meters), "stacked-meters");
      return "Meters on the scoped equipment; NF has no gas meter role, so this stacks electric meters.";
    },
  });
})();
