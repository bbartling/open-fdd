// GENERATED COPY of shared/static/version.js by scripts/nf/sync_shared.py: edit the source, then re-run the script.
// App version in the header: "v5.0.0 · abc1234", linked to that exact commit on GitHub.
// version.json is generated at deploy time by scripts/nf/hooks/nf_app_sync.py from the repo's
// VERSION file + `git rev-parse HEAD` (never committed, never edited by hand), so what a box
// shows always maps to the open-fdd revision that was pushed to it. Dev mock serves the same.
//
// The Full app also shows which server engine `auto` would run. Charts themselves stay on the NF
// history API. Lite has no FDD engine, so it shows no badge. There is no DuckDB-WASM.

/** Label for the NF plugin engine. `auto` matches pickEngine: Timescale when that option is set, else DuckDB. */
function engineBadgeText(options) {
  const engine = String((options && options.engine) || "auto");
  if (engine === "timescale") return "Timescale";
  if (engine === "sqlite") return "SQLite (deprecated)";
  if (engine === "pglite") return "PGlite (deprecated)";
  if (engine === "duckdb") return "DuckDB";
  if (options && options.timescale) return "Timescale";
  return "DuckDB";
}

function appOptions(body) {
  const list = Array.isArray(body) ? body : (body && (body.applications || body.apps)) || [];
  const app = list.find((item) => item && (item.id === "open-fdd" || (item.application && item.application.id === "open-fdd")));
  if (!app) return null;
  return app.options || (app.application && app.application.options) || {};
}

if (typeof document !== "undefined") {
  const REPO = "https://github.com/bbartling/open-fdd";
  async function mount() {
    const h1 = document.querySelector("header h1");
    if (!h1) return;
    let v;
    try {
      const r = await fetch("version.json", { cache: "no-store", credentials: "same-origin" });
      if (!r.ok) return;
      v = await r.json();
    } catch (e) {
      return;
    }
    if (!v || !v.version) return;
    const a = document.createElement("a");
    a.className = "app-version";
    const sha = (v.commit || "").slice(0, 7);
    a.textContent = `v${v.version}${sha ? ` · ${sha}` : ""}${v.dirty ? "+" : ""}`;
    a.href = v.commit ? `${REPO}/tree/${v.commit}` : `${REPO}/releases`;
    a.target = "_blank";
    a.rel = "noopener";
    a.title = `Open-FDD ${v.version}${v.commit ? `, commit ${v.commit}` : ""}${v.dirty ? " (local changes)" : ""}`
      + (v.deployed ? `, deployed ${v.deployed}` : "");
    h1.insertAdjacentElement("afterend", a);
    if (/\/open-fdd-lite(\/|$)/.test(location.pathname)) return;
    try {
      const r = await fetch("/api/v1/apps", { cache: "no-store", credentials: "same-origin" });
      if (!r.ok) return;
      const options = appOptions(await r.json());
      if (!options) return;
      const badge = document.createElement("span");
      badge.className = "engine-badge";
      badge.textContent = engineBadgeText(options);
      a.insertAdjacentElement("afterend", badge);
    } catch (e) { /* the version link stands without an engine label */ }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
}

if (typeof module !== "undefined" && module.exports) module.exports = { engineBadgeText, appOptions };
