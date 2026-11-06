// Chart catalog for Open-FDD Lite. Each chart says which points it needs (by tags), which
// ranges it offers and how NF should resample them, so only one small request goes
// out per chart and nothing is fetched for charts that aren't on screen.
//
// NF resamples server side: /api/v1/point/data?...&window=<s>s&method=AVERAGE|MIN|MAX
// returns one value per window (7 days of one sensor: 916 KB raw vs 14 KB hourly).
// Used by the Charts tab (app.js) and the standalone chart.html. Needs nf.js + model.js.

const PALETTE = LT.palette;
const unitLabel = (u) => u || "";
const parseTs = (ts) => Date.parse(ts.replace(/(\.\d{3})\d+/, "$1"));
const fmt = (v, d = 1) => (v == null || isNaN(v) ? "–" : v.toFixed(d));
const latestOf = (p) => p.latest?.double ?? p.latest?.real;

const axisStyle = {
  axisLine: { lineStyle: { color: LT.axisLine } },
  axisLabel: { color: LT.label },
  splitLine: { lineStyle: { color: LT.split } },
};
const tooltip = { trigger: "axis", backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText } };
const zoom = (bottom = 8) => [{ type: "inside" }, { type: "slider", height: 18, bottom, borderColor: LT.axisLine,
  fillerColor: LT.filler, textStyle: { color: LT.label } }];
const legend = { top: 0, textStyle: { color: LT.legend } };

// ---- which points, by tags (shared with app.js) ------------------------------------
// Sensors first, temps first, then setpoints; ties by label.
const rank = (p) => (has(p, "sensor") ? 0 : 2) + (isTemp(p) ? 0 : 1);

/** Point sets for a site (and optionally one equip): cards/charts, status, weather. */
function pointSets(model, site, equip) {
  const equipIds = model.equips.filter((e) => (e.attrs || {}).siteRef === site).map(idOf);
  const inScope = (p) => p.equipRef && (equip ? p.equipRef === equip : equipIds.includes(p.equipRef));
  const tagged = model.points.filter((p) => p.siteRef === site && has(p, "point"));
  const equipPts = tagged.filter(inScope);
  return {
    cards: equipPts
      .filter((p) => p.kind === "Number" && has(p, "his") && !has(p, "spare") && (has(p, "sensor") || has(p, "sp")))
      .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)),
    status: equipPts.filter((p) => p.kind === "Bool" && !has(p, "spare"))
      .sort((a, b) => a.equipRef.localeCompare(b.equipRef) || a.name.localeCompare(b.name)),
    weather: tagged.filter((p) => has(p, "weather")).sort((a, b) => a.name.localeCompare(b.name)),
  };
}

// Outside air temp + humidity sensors on one equip, found by markers.
function rhPair(points) {
  const t = points.find((p) => has(p, "outside", "air", "temp", "sensor"));
  const rh = points.find((p) => has(p, "outside", "air", "humidity", "sensor") && p.equipRef === t?.equipRef);
  return t && rh ? [t, rh] : null;
}

function dewPointF(tF, rh) {
  const tC = (tF - 32) / 1.8, a = 17.62, b = 243.12;
  const g = Math.log(rh / 100) + (a * tC) / (b + tC);
  return ((b * g) / (a - g)) * 1.8 + 32;
}

// ---- history: resampled by NF, cached briefly ---------------------------------------
const WINDOWS = [60, 300, 600, 900, 1800, 3600, 7200, 14400, 86400];

/** Smallest window giving at most ~`target` values per series over `hours`. */
const pickWindow = (hours, target = 360) => WINDOWS.find((w) => (hours * 3600) / w <= target) || 86400;

const seriesCache = new Map();  // url -> { at, promise }
const CACHE_MS = 60e3;

/**
 * uuid -> [[ms, value], ...] for `list` over the last `hours`, one value per window.
 * One request for all points; repeat calls within a minute reuse the answer.
 */
async function fetchSeries(list, hours, { method = "AVERAGE", windowSec = pickWindow(hours) } = {}) {
  const out = new Map(list.map((p) => [p.uuid, []]));
  if (!list.length) return out;
  // Round the end to the window so repeat views share a cache entry.
  const end = Math.ceil(Date.now() / (windowSec * 1e3)) * windowSec * 1e3;
  const from = new Date(end - hours * 3600e3).toISOString(), to = new Date(end).toISOString();
  const uuids = list.map((p) => "uuids=" + encodeURIComponent(p.uuid)).join("&");
  const url = `/api/v1/point/data?${uuids}&from=${from}&to=${to}&window=${windowSec}s&method=${method}`;
  let hit = seriesCache.get(url);
  if (!hit || Date.now() - hit.at > CACHE_MS) {
    hit = { at: Date.now(), promise: api(url) };
    seriesCache.set(url, hit);
    hit.promise.catch(() => seriesCache.delete(url));
    for (const [k, v] of seriesCache) if (Date.now() - v.at > CACHE_MS) seriesCache.delete(k);
  }
  for (const series of (await hit.promise).data || []) {
    const arr = out.get(series.uuid);
    if (!arr) continue;
    for (const s of series.values || []) {
      const v = s.double ?? s.real;
      if (v != null && s.ts) arr.push([parseTs(s.ts), v]);
    }
    arr.sort((a, b) => a[0] - b[0]);
  }
  return out;
}

const localDay = (t) => new Date(t).toLocaleDateString(undefined, { weekday: "short", month: "numeric", day: "numeric" });

/** Group [[ms, v]] by local calendar day -> Map(day -> values[]), days in time order. */
function byDay(arr) {
  const m = new Map();
  for (const [t, v] of arr) {
    const k = localDay(t);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(v);
  }
  return m;
}

const lineSeries = (p, data, extra = {}) => ({
  name: p.name, type: "line", showSymbol: false, smooth: 0.2, lineStyle: { width: 1.6 },
  emphasis: { focus: "series" }, data, ...extra,
});

// ---- the catalog --------------------------------------------------------------------
// ctx = { cards, status, weather } from pointSets(). Each entry:
//   applies(ctx)      chart makes sense for these points (else hidden)
//   ranges / range    offered + default hours
//   pick(ctx)         optional: points for a picker; build gets opt.point
//   build(ctx, hours, opt) -> { option, hint }   (fetches only what it draws)
const CHARTS = [
  {
    id: "temps", title: "Temperatures", desc: "Every temperature sensor and setpoint on the equip",
    ranges: [6, 24, 72, 168], range: 24,
    applies: (c) => c.cards.some(isTemp),
    async build(c, hours) {
      const temps = c.cards.filter(isTemp);
      const s = await fetchSeries(temps, hours);
      return {
        hint: `${temps.length} points · ${pickWindow(hours) / 60} min averages`,
        option: {
          color: PALETTE, tooltip, legend, grid: { left: 50, right: 20, top: 36, bottom: 60 },
          xAxis: { type: "time", ...axisStyle },
          yAxis: { type: "value", scale: true, name: unitLabel(temps[0]?.units), nameTextStyle: { color: LT.label }, ...axisStyle },
          dataZoom: zoom(),
          series: temps.map((p) => lineSeries(p, s.get(p.uuid))),
        },
      };
    },
  },
  {
    id: "weather", title: "Weather vs outside air", desc: "Weather-service values next to the equip's outside air sensors",
    ranges: [24, 48, 168], range: 48,
    applies: (c) => c.weather.length > 0,
    async build(c, hours) {
      const pair = rhPair(c.cards) || [];
      const s = await fetchSeries([...pair, ...c.weather], hours);
      const line = (p, axis, dashed) => ({
        name: p.name, type: "line", yAxisIndex: axis, data: s.get(p.uuid), showSymbol: dashed, symbolSize: 4,
        step: dashed ? "end" : false, smooth: !dashed, lineStyle: { width: dashed ? 2 : 1.4, type: dashed ? "dashed" : "solid" },
      });
      return {
        hint: "dashed = weather service, solid = equipment sensors",
        option: {
          color: [PALETTE[1], PALETTE[6], PALETTE[2], PALETTE[0], PALETTE[3], PALETTE[4]], tooltip, legend,
          grid: { left: 50, right: 50, top: 36, bottom: 60 },
          xAxis: { type: "time", ...axisStyle },
          yAxis: [
            { type: "value", scale: true, name: "°F", nameTextStyle: { color: LT.label }, ...axisStyle },
            { type: "value", scale: true, name: "%RH", position: "right", nameTextStyle: { color: LT.label }, ...axisStyle, splitLine: { show: false } },
          ],
          dataZoom: zoom(),
          series: [...pair.map((p) => line(p, isRH(p) ? 1 : 0, false)), ...c.weather.map((p) => line(p, isRH(p) ? 1 : 0, true))],
        },
      };
    },
  },
  {
    id: "heatmap", title: "Hour-of-day heatmap", desc: "One sensor's hourly average, day by day",
    ranges: [72, 168], range: 168,
    applies: (c) => c.cards.length > 0,
    pick: (c) => c.cards,
    defaultPick: (c) => (c.cards.find((p) => has(p, "discharge", "air", "temp")) || c.cards[0])?.uuid,
    async build(c, hours, opt) {
      const p = c.cards.find((x) => x.uuid === opt.point) || c.cards[0];
      const arr = (await fetchSeries([p], hours, { windowSec: 3600 })).get(p.uuid);
      const days = [];
      const data = arr.map(([t, v]) => {
        const day = localDay(t);
        if (!days.includes(day)) days.push(day);
        return [new Date(t).getHours(), days.indexOf(day), +v.toFixed(2)];
      });
      const vals = data.map((d) => d[2]);
      return {
        hint: `${p.dis} · hourly averages, local time`,
        option: {
          tooltip: { position: "top", backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText },
            formatter: (x) => `${days[x.value[1]]} ${x.value[0]}:00<br><b>${x.value[2]} ${unitLabel(p.units)}</b>` },
          grid: { left: 90, right: 20, top: 10, bottom: 80 },
          xAxis: { type: "category", data: [...Array(24).keys()].map(String), ...axisStyle },
          yAxis: { type: "category", data: days, ...axisStyle },
          visualMap: {
            min: Math.min(...vals), max: Math.max(...vals), calculable: true, orient: "horizontal", left: "center", bottom: 0,
            itemHeight: 220, textStyle: { color: LT.label },
            inRange: { color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#f94144"] },
          },
          series: [{ type: "heatmap", data, itemStyle: { borderColor: LT.panel, borderWidth: 2, borderRadius: 3 } }],
        },
      };
    },
  },
  {
    id: "daily", title: "Daily min / mean / max", desc: "Each temperature's range per day",
    ranges: [72, 168], range: 168,
    applies: (c) => c.cards.some(isTemp),
    async build(c, hours) {
      const temps = c.cards.filter(isTemp);
      // Hourly MIN / MAX / AVERAGE from NF, folded into local days here (NF's daily
      // windows are UTC-aligned). 3 small requests instead of every raw sample.
      const [lo, hi, avg] = await Promise.all(["MIN", "MAX", "AVERAGE"].map((method) =>
        fetchSeries(temps, hours, { method, windowSec: 3600 })));
      const days = [...byDay(avg.get(temps[0].uuid) || []).keys()];
      return {
        hint: "hourly MIN / MAX / AVERAGE from NF, grouped by local day",
        option: {
          color: PALETTE, legend,
          tooltip: { trigger: "item", backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText },
            formatter: (x) => `${x.seriesName} · ${x.name}<br>min ${fmt(x.value[3])} · mean ${fmt((x.value[1] + x.value[2]) / 2)} · max ${fmt(x.value[4])}` },
          grid: { left: 50, right: 20, top: 36, bottom: 30 },
          xAxis: { type: "category", data: days, ...axisStyle },
          yAxis: { type: "value", scale: true, name: unitLabel(temps[0]?.units), nameTextStyle: { color: LT.label }, ...axisStyle },
          // Candlestick as a range bar: open/close = mean (thin), low/high = min/max.
          series: temps.map((p, i) => {
            const L = byDay(lo.get(p.uuid)), H = byDay(hi.get(p.uuid)), A = byDay(avg.get(p.uuid));
            const col = PALETTE[i % PALETTE.length];
            return {
              name: p.name, type: "candlestick", barMaxWidth: 10,
              itemStyle: { color: col, color0: col, borderColor: col, borderColor0: col },
              data: days.map((d) => {
                if (!A.has(d)) return ["-", "-", "-", "-"];
                const a = A.get(d), m = a.reduce((x, y) => x + y, 0) / a.length;
                return [m - 0.15, m + 0.15, Math.min(...(L.get(d) || a)), Math.max(...(H.get(d) || a))];
              }),
            };
          }),
        },
      };
    },
  },
  {
    id: "runtime", title: "Equipment runtime", desc: "Hours on per day for each on/off point (fan, heat, …)",
    ranges: [72, 168], range: 168,
    applies: (c) => c.status.length > 0,
    async build(c, hours) {
      // Hourly AVERAGE of a 0/1 point = fraction of that hour it was on.
      const s = await fetchSeries(c.status, hours, { windowSec: 3600 });
      const days = [...byDay(s.get(c.status[0].uuid) || []).keys()];
      return {
        hint: "from hourly averages of each Bool point",
        option: {
          color: PALETTE, legend, tooltip: { ...tooltip, valueFormatter: (v) => `${fmt(v)} h` },
          grid: { left: 50, right: 20, top: 36, bottom: 30 },
          xAxis: { type: "category", data: days, ...axisStyle },
          yAxis: { type: "value", name: "hours on", max: 24, nameTextStyle: { color: LT.label }, ...axisStyle },
          series: c.status.map((p) => {
            const D = byDay(s.get(p.uuid));
            return { name: p.name, type: "bar", barMaxWidth: 18,
              data: days.map((d) => +(D.get(d) || []).reduce((a, b) => a + b, 0).toFixed(2)) };
          }),
        },
      };
    },
  },
  {
    id: "psy", title: "Outdoor air: temp vs humidity", desc: "Outside air temp against humidity, colored by time of day",
    ranges: [24, 168], range: 168,
    applies: (c) => !!rhPair(c.cards),
    async build(c, hours) {
      const [t, rh] = rhPair(c.cards);
      const s = await fetchSeries([t, rh], hours, { windowSec: 900 });
      const rhAt = new Map(s.get(rh.uuid));
      const pts = s.get(t.uuid).filter(([k]) => rhAt.has(k))
        .map(([k, tv]) => [tv, rhAt.get(k), new Date(k).getHours() + new Date(k).getMinutes() / 60, k]);
      const lastT = latestOf(t), lastRH = latestOf(rh);
      return {
        hint: `${t.name} × ${rh.name} · 15 min averages · white = now`,
        option: {
          tooltip: { backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText },
            formatter: (x) => `${new Date(x.value[3] ?? Date.now()).toLocaleString()}<br>${fmt(x.value[0])} ${unitLabel(t.units)} · ${fmt(x.value[1])} %RH`
              + (/F$/.test(t.units) ? `<br>dew point ${fmt(dewPointF(x.value[0], x.value[1]))} °F` : "") },
          grid: { left: 50, right: 70, top: 20, bottom: 40 },
          xAxis: { type: "value", scale: true, name: unitLabel(t.units), nameLocation: "center", nameGap: 26, nameTextStyle: { color: LT.label }, ...axisStyle },
          yAxis: { type: "value", scale: true, name: "%RH", nameTextStyle: { color: LT.label }, ...axisStyle },
          visualMap: { dimension: 2, min: 0, max: 24, right: 0, top: "middle", itemHeight: 180, calculable: false,
            text: ["24h", "0h"], textStyle: { color: LT.label },
            inRange: { color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#3a0ca3"] }, seriesIndex: 0 },
          series: [
            { type: "scatter", data: pts, symbolSize: 6, itemStyle: { opacity: 0.75 } },
            { type: "scatter", data: lastT != null && lastRH != null ? [[lastT, lastRH]] : [], symbolSize: 14,
              itemStyle: { color: "#ffffff", borderColor: "#4cc9f0", borderWidth: 3 }, z: 10 },
          ],
        },
      };
    },
  },
  {
    id: "other", title: "Other signals", desc: "Non-temperature, non-humidity sensors (pressure, position, …)",
    ranges: [6, 24, 72, 168], range: 24,
    applies: (c) => c.cards.some((p) => !isTemp(p) && !isRH(p)),
    async build(c, hours) {
      const others = c.cards.filter((p) => !isTemp(p) && !isRH(p)).slice(0, 2);
      const s = await fetchSeries(others, hours);
      return {
        hint: `${pickWindow(hours) / 60} min averages`,
        option: {
          color: PALETTE.slice(3), tooltip, legend, grid: { left: 50, right: 50, top: 36, bottom: 60 },
          xAxis: { type: "time", ...axisStyle },
          yAxis: others.map((p, i) => ({
            type: "value", scale: true, name: unitLabel(p.units), position: i ? "right" : "left",
            nameTextStyle: { color: LT.label }, ...axisStyle, splitLine: { show: !i, lineStyle: { color: LT.split } },
          })),
          dataZoom: zoom(),
          series: others.map((p, i) => lineSeries(p, s.get(p.uuid), { yAxisIndex: i, smooth: false, areaStyle: { opacity: 0.08 } })),
        },
      };
    },
  },
];

const chartDef = (id) => CHARTS.find((c) => c.id === id);
const rangeLabel = (h) => (h < 48 ? `${h}h` : `${h / 24}d`);

/**
 * Draw one catalog chart into `chart` (an echarts instance). Returns the hint text.
 * Late answers from an earlier call on the same instance are dropped.
 */
async function drawChart(chart, def, ctx, hours, opt = {}) {
  const ticket = (chart.__ticket = (chart.__ticket || 0) + 1);
  chart.showLoading({ text: "", color: LT.palette[0], maskColor: LT.dark ? "rgba(11,16,32,0.35)" : "rgba(255,255,255,0.5)" });
  try {
    const { option, hint } = await def.build(ctx, hours, opt);
    if (chart.__ticket !== ticket) return null;
    chart.setOption({ animationDuration: 300, ...option }, true);
    return hint;
  } finally {
    if (chart.__ticket === ticket) chart.hideLoading();
  }
}
