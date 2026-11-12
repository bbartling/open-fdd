// GENERATED COPY of shared/static/theme.js by scripts/nf/sync_shared.py: edit the source, then re-run the script.
// Open-FDD UI themes (same tokens as Open-FDD 4.x): light "blueprint" (default)
// and dark. CSS switches on <html data-theme>; charts use two registered ECharts themes.
// Renderers build theme-free options; ofddRender() adds the shared behavior (Save PNG,
// linked time zoom, CSP-safe tooltips). Needs echarts-global.js (module) loaded first.

const THEME_KEY = "openfdd-ui-theme";

const axisTheme = (line, label, split) => ({
  axisLine: { lineStyle: { color: line } }, axisTick: { lineStyle: { color: line } },
  axisLabel: { color: label }, splitLine: { lineStyle: { color: split } }, nameTextStyle: { color: label },
});

const OFDD_THEMES = {
  light: {
    name: "ofdd-light",
    def: {
      color: ["#e11d48", "#ea580c", "#ca8a04", "#16a34a", "#0d9488", "#2563eb",
        "#7c3aed", "#db2777", "#0891b2", "#65a30d", "#9333ea", "#dc2626"],
      backgroundColor: "#ffffff",
      textStyle: { color: "#1e3a8a" },
      title: { textStyle: { color: "#1e3a8a", fontSize: 14 } },
      legend: { textStyle: { color: "#334155" } },
      tooltip: { backgroundColor: "#ffffffee", borderColor: "#2563eb", textStyle: { color: "#0f172a" } },
      categoryAxis: axisTheme("#2563eb", "#475569", "#e2e8f0"),
      valueAxis: axisTheme("#2563eb", "#475569", "#e2e8f0"),
      timeAxis: axisTheme("#2563eb", "#475569", "#e2e8f0"),
      visualMap: { textStyle: { color: "#475569" } },
      dataZoom: { textStyle: { color: "#475569" }, borderColor: "#cbd5e1", fillerColor: "rgba(37,99,235,0.12)" },
      toolbox: { iconStyle: { borderColor: "#475569" } },
    },
  },
  dark: {
    name: "ofdd-dark",
    def: {
      color: ["#4cc9f0", "#f8961e", "#f94144", "#90be6d", "#b5179e", "#f9c74f", "#43aa8b", "#577590"],
      backgroundColor: "transparent",
      textStyle: { color: "#e6ebf5" },
      title: { textStyle: { color: "#c9d2e8", fontSize: 14 } },
      legend: { textStyle: { color: "#c9d2e8" } },
      tooltip: { backgroundColor: "#0f1730ee", borderColor: "#2b3858", textStyle: { color: "#e6ebf5" } },
      categoryAxis: axisTheme("#2b3858", "#8a96b3", "#1c2640"),
      valueAxis: axisTheme("#2b3858", "#8a96b3", "#1c2640"),
      timeAxis: axisTheme("#2b3858", "#8a96b3", "#1c2640"),
      visualMap: { textStyle: { color: "#8a96b3" } },
      dataZoom: { textStyle: { color: "#8a96b3" }, borderColor: "#2b3858", fillerColor: "rgba(76,201,240,0.13)" },
      toolbox: { iconStyle: { borderColor: "#8a96b3" } },
    },
  },
};
for (const t of Object.values(OFDD_THEMES)) echarts.registerTheme(t.name, t.def);

// Red fault lanes (for fault series on time charts).
const FAULT_LANE = { lineStyle: { color: "rgba(220,38,38,0.9)", width: 0.8 }, areaStyle: { color: "rgba(239,68,68,0.35)" } };

const themeName = () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
const palette = () => OFDD_THEMES[themeName()].def.color;
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---- chart instances: one per element, recreated with the new theme on a switch ------
const mounted = new Set();

/** The ECharts instance for `el` in the active theme (created on first use). */
function ofddChart(el) {
  for (const old of mounted) if (!old.isConnected) { echarts.getInstanceByDom(old)?.dispose(); mounted.delete(old); }
  mounted.add(el);
  return echarts.getInstanceByDom(el) || echarts.init(el, OFDD_THEMES[themeName()].name, { renderer: "canvas" });
}

function ofddResizeAll() {
  for (const el of mounted) if (el.offsetParent) echarts.getInstanceByDom(el)?.resize();
}

const safeStem = (s) => String(s || "chart").replace(/[^\w.-]+/g, "_").slice(0, 80);
const tipNum = (v) => (typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2)) : esc(v ?? "–"));

// Axis tooltips built from markup + classes only (the CSP blocks style attributes, which
// ECharts' default markers use). Marker color = the series' index in the theme palette.
function axisTooltip(suffix = "") {
  return (params) => {
    const rows = Array.isArray(params) ? params : [params];
    if (!rows.length) return "";
    const pal = palette();
    const head = `<div class="tip-head">${esc(rows[0].axisValueLabel ?? rows[0].name ?? "")}</div>`;
    return head + rows.map((p) => {
      const v = Array.isArray(p.value) ? p.value[p.value.length - 1] : p.value;
      const i = pal.indexOf(p.color);
      return `<div class="tip-row"><span class="mk ${i >= 0 ? `mk${i}` : ""}"></span>${esc(p.seriesName)}`
        + `<b>${tipNum(v)}${esc(suffix)}</b></div>`;
    }).join("");
  };
}

/** Shared behavior on top of a theme-free option. */
function ofddFinish(option, name) {
  const o = { ...option };
  o.toolbox = { right: 8, top: 4, feature: { saveAsImage: { pixelRatio: 2, name: safeStem(name), title: "Save PNG" } } };
  const xs = [].concat(o.xAxis || []);
  if (o.dataZoom !== false && xs.length && xs.some((x) => x.type === "time" || x.type === "category")) {
    // Linked time zoom: one inside zoom + one slider driving every x-axis.
    o.dataZoom = [{ type: "inside", xAxisIndex: "all" }, { type: "slider", xAxisIndex: "all", height: 22, bottom: 4 }];
  } else if (o.dataZoom === false) {
    delete o.dataZoom;
  }
  if (o.tooltip && o.tooltip.trigger === "axis" && !o.tooltip.formatter) {
    const { suffix, ...rest } = o.tooltip;
    o.tooltip = { ...rest, formatter: axisTooltip(suffix) };
  }
  return o;
}

/** Render a theme-free option into `chart` and mark its frame as drawn (solid border). */
function ofddRender(chart, option, name) {
  chart.setOption(ofddFinish(option, name), true);
  chart.getDom().classList.add("rendered");
}

// ---- switching ------------------------------------------------------------------------
const themeListeners = [];
const onThemeChange = (fn) => themeListeners.push(fn);

function setTheme(t) {
  t = t === "dark" ? "dark" : "light";
  try { localStorage.setItem(THEME_KEY, t); } catch { /* storage blocked */ }
  document.documentElement.dataset.theme = t;
  for (const el of mounted) echarts.getInstanceByDom(el)?.dispose();
  syncThemeToggle();
  themeListeners.forEach((fn) => fn(t));
}

function syncThemeToggle() {
  const b = document.getElementById("themeToggle");
  if (!b) return;
  const dark = themeName() === "dark";
  b.textContent = dark ? "☀ light" : "☾ dark";
  b.title = `Switch to the ${dark ? "light (blueprint)" : "dark"} theme`;
}

document.addEventListener("DOMContentLoaded", () => {
  syncThemeToggle();
  document.getElementById("themeToggle")?.addEventListener("click", () => setTheme(themeName() === "dark" ? "light" : "dark"));
  window.addEventListener("resize", ofddResizeAll);
});
