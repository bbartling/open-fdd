// App version in the header: "v5.0.0 · abc1234", linked to that exact commit on GitHub.
// version.json is generated at deploy time by scripts/nf/hooks/nf_app_sync.py from the repo's
// VERSION file + `git rev-parse HEAD` (never committed, never edited by hand), so what a box
// shows always maps to the open-fdd revision that was pushed to it. Dev mock serves the same.
(function () {
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
  }
  function showEngineError(text) {
    const err = document.getElementById("err");
    if (!document.getElementById("engineBuild") || !text || !err) return;
    err.textContent = text;
    err.classList.add("show");
  }
  function errorFromRun(run) {
    const blobs = [];
    const results = (run && run.results) || {};
    for (const g of Object.values(results)) {
      if (!g || typeof g !== "object") continue;
      if (g.result) blobs.push(g.result);
      for (const e of g.events || []) if (e && e.message) blobs.push(e.message);
    }
    for (const b of blobs) {
      if (b && typeof b === "object" && b.engine_error) return String(b.engine_error);
      if (typeof b === "string") {
        try { const j = JSON.parse(b); if (j && j.engine_error) return String(j.engine_error); } catch (e) { /* log line is not JSON */ }
        if (b.startsWith("DuckDB engine failed to load:")) return b;
      }
    }
    return "";
  }
  async function engineHealth() {
    if (!document.getElementById("engineBuild") || typeof api !== "function") return;
    const app = (location.pathname.match(/\/apps\/static\/([^/]+)/) || [])[1] || "open-fdd";
    try {
      const started = await api(`/api/v1/apps/${app}/hooks/schema`, {});
      if (started && started.engine_error) { showEngineError(started.engine_error); return; }
      const pid = started && started.pid;
      if (!pid) return;
      const deadline = Date.now() + 20000;
      let waitMs = 1000;
      while (Date.now() < deadline) {
        const runs = await api(`/api/v1/apps/${app}/hooks/schema/runs?page_size=5&include_results=true`);
        const hit = ((runs && runs.runs) || []).find((r) => String(r.pid) === String(pid));
        const msg = hit && errorFromRun(hit);
        if (msg) { showEngineError(msg); return; }
        const state = String((hit && (hit.state || hit.status)) || "");
        if (hit && /SUCCESS|FAIL|ERROR|CANCEL/.test(state)) return;
        await new Promise((ok) => setTimeout(ok, waitMs));
        waitMs = Math.min(waitMs * 1.5, 5000);
      }
    } catch (e) { /* the badge still names the build */ }
  }
  function start() { mount(); engineHealth(); }
  if (document.readyState === "complete") start();
  else document.addEventListener("DOMContentLoaded", start);
})();
