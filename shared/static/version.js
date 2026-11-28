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
  const BACKEND_LABEL = { duckdb: "DuckDB backend", timescale: "Timescale backend" };
  function showEngineError(text) {
    const err = document.getElementById("err");
    if (!document.getElementById("engineBuild") || !text || !err) return;
    err.textContent = text;
    err.classList.add("show");
  }
  function applyBackendLabel(id, label) {
    const badge = document.getElementById("engineBuild");
    if (!badge) return;
    const text = label || BACKEND_LABEL[id] || "";
    if (!text) return;
    badge.textContent = text;
    if (id === "duckdb" || id === "timescale") badge.dataset.ofddEngine = id;
  }
  function payloadFrom(blob) {
    const out = { id: "", label: "", error: "" };
    const take = (b) => {
      if (!b) return;
      if (typeof b === "string") {
        if (b.startsWith("DuckDB engine failed to load:")) out.error = out.error || b;
        try { b = JSON.parse(b); } catch (e) { return; }
      }
      if (!b || typeof b !== "object") return;
      if (b.engine === "duckdb" || b.engine === "timescale") out.id = b.engine;
      if (b.engine_label) out.label = String(b.engine_label);
      if (b.engine_error) out.error = String(b.engine_error);
    };
    take(blob);
    return out;
  }
  function payloadFromRun(run) {
    const found = { id: "", label: "", error: "" };
    const blobs = [];
    const results = (run && run.results) || {};
    for (const g of Object.values(results)) {
      if (!g || typeof g !== "object") continue;
      if (g.result) blobs.push(g.result);
      for (const e of g.events || []) if (e && e.message) blobs.push(e.message);
    }
    for (const b of blobs) {
      const one = payloadFrom(b);
      if (one.id) found.id = one.id;
      if (one.label) found.label = one.label;
      if (one.error) found.error = one.error;
    }
    return found;
  }
  async function engineHealth() {
    if (!document.getElementById("engineBuild") || typeof api !== "function") return;
    const app = (location.pathname.match(/\/apps\/static\/([^/]+)/) || [])[1] || "open-fdd";
    // This install has no schema hook. Its only engine is DuckDB. Calling schema would 404.
    if (app === "open-fdd-lite") { applyBackendLabel("duckdb"); return; }
    try {
      if (typeof whenAuthReady === "function") await whenAuthReady();
      const started = await api(`/api/v1/apps/${app}/hooks/schema`, {}, { method: "POST" });
      const first = payloadFrom(started);
      applyBackendLabel(first.id, first.label);
      if (first.error) { showEngineError(first.error); return; }
      const pid = started && started.pid;
      if (!pid) return;
      const deadline = Date.now() + 20000;
      let waitMs = 1000;
      while (Date.now() < deadline) {
        const runs = await api(`/api/v1/apps/${app}/hooks/schema/runs?page_size=5&include_results=true&include_logs=true`);
        const hit = ((runs && runs.runs) || []).find((r) => String(r.pid) === String(pid));
        const got = hit && payloadFromRun(hit);
        if (got && (got.id || got.label)) applyBackendLabel(got.id, got.label);
        if (got && got.error) { showEngineError(got.error); return; }
        const state = String((hit && (hit.state || hit.status)) || "");
        if (hit && /SUCCESS|FAIL|ERROR|CANCEL/.test(state)) return;
        await new Promise((ok) => setTimeout(ok, waitMs));
        waitMs = Math.min(waitMs * 1.5, 5000);
      }
    } catch (e) { /* the badge stays on the last label that resolved */ }
  }
  function start() { mount(); engineHealth(); }
  if (document.readyState === "complete") start();
  else document.addEventListener("DOMContentLoaded", start);
})();
