// Open-FDD Lite theme: the same light "blueprint" (default) / dark switch as the full
// Open-FDD NF app (same <html data-theme> + localStorage key "openfdd-ui-theme", set
// before first paint by theme-init.js). CSS follows the tokens in style.css; charts
// read their colors from `LT` below. Switching reloads the page: pages are small and
// this keeps Lite free of per-chart re-theming code.
// Classic script, no dependencies. Load after theme-init.js and before charts.js.

const LT_DARK = {
  dark: true,
  palette: ["#4cc9f0", "#f8961e", "#f94144", "#90be6d", "#b5179e", "#f9c74f", "#43aa8b", "#577590"],
  axisLine: "#2b3858", label: "#8a96b3", split: "#1c2640", legend: "#c9d2e8",
  tipBg: "#0f1730ee", tipLine: "#2b3858", tipText: "#e6ebf5", filler: "#4cc9f022", panel: "#121a30",
};
const LT_LIGHT = {
  dark: false,
  palette: ["#e11d48", "#ea580c", "#ca8a04", "#16a34a", "#0d9488", "#2563eb", "#7c3aed", "#db2777"],
  axisLine: "#2563eb", label: "#475569", split: "#e2e8f0", legend: "#334155",
  tipBg: "#ffffffee", tipLine: "#2563eb", tipText: "#0f172a", filler: "rgba(37,99,235,0.12)", panel: "#ffffff",
};
const LT = document.documentElement.dataset.theme === "dark" ? LT_DARK : LT_LIGHT;

document.addEventListener("DOMContentLoaded", () => {
  const b = document.getElementById("themeToggle");
  if (!b) return;
  b.textContent = LT.dark ? "☀ light" : "☾ dark";
  b.title = `Switch to the ${LT.dark ? "light (blueprint)" : "dark"} theme`;
  b.addEventListener("click", () => {
    try { localStorage.setItem("openfdd-ui-theme", LT.dark ? "light" : "dark"); } catch { /* storage blocked */ }
    location.reload();
  });
});
