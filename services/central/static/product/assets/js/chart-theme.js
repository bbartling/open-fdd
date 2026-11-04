/**
 * ECharts themes + shared chart tokens (light blueprint default, dark Bench Viz).
 * Renderers return theme-free options; mountChart applies the active theme.
 */
import * as echarts from "../vendor/echarts.esm.min.js";

export const STORAGE_KEY = "openfdd-ui-theme";

export const RAINBOW_PALETTE = [
  "#e11d48",
  "#ea580c",
  "#ca8a04",
  "#16a34a",
  "#0d9488",
  "#2563eb",
  "#7c3aed",
  "#db2777",
  "#0891b2",
  "#65a30d",
  "#9333ea",
  "#dc2626",
];

export function rainbowColor(index) {
  return RAINBOW_PALETTE[((index % RAINBOW_PALETTE.length) + RAINBOW_PALETTE.length) % RAINBOW_PALETTE.length];
}

const LIGHT_THEME = {
  color: RAINBOW_PALETTE,
  backgroundColor: "#ffffff",
  textStyle: { color: "#1e3a8a" },
  title: { textStyle: { color: "#1e3a8a", fontSize: 14 } },
  legend: { textStyle: { color: "#334155" } },
  tooltip: {
    backgroundColor: "#ffffffee",
    borderColor: "#2563eb",
    textStyle: { color: "#0f172a" },
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: "#2563eb" } },
    axisLabel: { color: "#475569" },
    splitLine: { lineStyle: { color: "#e2e8f0" } },
  },
  valueAxis: {
    axisLine: { lineStyle: { color: "#2563eb" } },
    axisLabel: { color: "#475569" },
    splitLine: { lineStyle: { color: "#e2e8f0" } },
  },
  timeAxis: {
    axisLine: { lineStyle: { color: "#2563eb" } },
    axisLabel: { color: "#475569" },
    splitLine: { lineStyle: { color: "#e2e8f0" } },
  },
};

const DARK_THEME = {
  color: ["#4cc9f0", "#f8961e", "#f94144", "#90be6d", "#b5179e", "#f9c74f", "#43aa8b", "#577590"],
  backgroundColor: "transparent",
  textStyle: { color: "#e6ebf5" },
  title: { textStyle: { color: "#c9d2e8", fontSize: 14 } },
  legend: { textStyle: { color: "#c9d2e8" } },
  tooltip: {
    backgroundColor: "#0f1730ee",
    borderColor: "#2b3858",
    textStyle: { color: "#e6ebf5" },
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: "#2b3858" } },
    axisLabel: { color: "#8a96b3" },
    splitLine: { lineStyle: { color: "#1c2640" } },
  },
  valueAxis: {
    axisLine: { lineStyle: { color: "#2b3858" } },
    axisLabel: { color: "#8a96b3" },
    splitLine: { lineStyle: { color: "#1c2640" } },
  },
  timeAxis: {
    axisLine: { lineStyle: { color: "#2b3858" } },
    axisLabel: { color: "#8a96b3" },
    splitLine: { lineStyle: { color: "#1c2640" } },
  },
};

let themesRegistered = false;

function registerThemes() {
  if (themesRegistered) return;
  echarts.registerTheme("ofdd-light", LIGHT_THEME);
  echarts.registerTheme("ofdd-dark", DARK_THEME);
  themesRegistered = true;
}

/** @returns {"light"|"dark"} */
export function readThemePreference() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "dark") return "dark";
  } catch {
    /* ignore */
  }
  return "light";
}

export function writeThemePreference(mode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode === "dark" ? "dark" : "light");
  } catch {
    /* ignore */
  }
  applyDocumentTheme(mode);
}

export function applyDocumentTheme(mode) {
  const dark = mode === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function activeEchartsThemeName() {
  return readThemePreference() === "dark" ? "ofdd-dark" : "ofdd-light";
}

export function ensureThemes() {
  registerThemes();
}

/** Toolbox saveAsImage with PNG stem (downloadFilename parity). */
export function toolboxSaveAsImage(stem) {
  const name = stem ? String(stem).replace(/[^\w.-]+/g, "_") : "openfdd-chart";
  return {
    show: true,
    feature: {
      saveAsImage: {
        title: "Save PNG",
        name,
        pixelRatio: 2,
      },
    },
    right: 8,
    top: 4,
  };
}

/** Linked time axes + bottom slider (FDD / inspect). */
export function linkedTimeZoom(xAxisCount) {
  const indices = [...Array(xAxisCount).keys()];
  return [
    { type: "inside", xAxisIndex: indices },
    {
      type: "slider",
      xAxisIndex: indices,
      height: 22,
      bottom: 4,
    },
  ];
}

export function faultLaneStyle() {
  return {
    line: { color: "rgba(220,38,38,0.9)", width: 0.8 },
    area: { color: "rgba(239,68,68,0.35)" },
  };
}

ensureThemes();
