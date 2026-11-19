// #1649: the dashboard's analytics are SQL (sql/analytics/*.sql). The browser has no SQL engine: it sends the aligned
// grid to the analytics hook (tool "sql_grid"), which runs the SQL in-process (hooks/lib/sql-analytics.js) and answers.
// This file is shared: the browser loads it as a script (globalThis.ofddSqlAnalytics, unless a host already set one,
// e.g. the hook's own sandbox), and the hook requires it for the wire format, so both ends encode and decode alike.
//
// Wire format (JSON, lossless): t as {t0, step, n} when the grid is uniform, else the array; each column run-length
// encoded as [[value, count], ...] (status columns collapse to a few runs). Runtime specs are made plain first: the
// site's week starts and occupied intervals are evaluated on the grid here, so no function crosses the wire.
(function (root) {
  "use strict";

  /** Runtime specs with weekOf / occ functions -> plain { key, motor, oat, weeks, occupied } (null when absent). */
  function plainRuntimeSpecs(t, specs) {
    return specs.map((s) => {
      const out = { key: s.key, motor: s.motor, oat: s.oat || null, weeks: null, occupied: null };
      if (Array.isArray(s.weeks)) out.weeks = s.weeks;
      else if (s.weekOf) {
        const starts = new Set();
        for (const x of t) { const k = s.weekOf(x); if (k != null && Number.isFinite(k)) starts.add(k); }
        out.weeks = [...starts].sort((a, b) => a - b);
      }
      if (Array.isArray(s.occupied)) out.occupied = s.occupied;
      else if (s.occ) {
        const iv = [];
        let open = null;
        for (let j = 0; j < t.length; j++) {
          const on = !!s.occ(t[j]);
          if (on && open == null) open = t[j];
          if (!on && open != null) { iv.push([open, t[j]]); open = null; }
        }
        if (open != null) iv.push([open, t[t.length - 1] + 1]);
        out.occupied = iv;
      }
      return out;
    });
  }

  const num = (v) => (v == null || !Number.isFinite(Number(v)) ? null : Number(v));

  function encodeGrid(g) {
    const t = Array.from(g.t);
    const step = t.length > 1 ? t[1] - t[0] : 0;
    const uniform = t.length > 1 && t.every((x, i) => i === 0 || x - t[i - 1] === step);
    const cols = {};
    for (const [k, v] of Object.entries(g.cols || {})) {
      if (!v) continue;
      const runs = [];
      for (let j = 0; j < t.length; j++) {
        const x = num(v[j]), last = runs[runs.length - 1];
        if (last && last[0] === x) last[1]++;
        else runs.push([x, 1]);
      }
      cols[k] = runs;
    }
    return { t: uniform ? { t0: t[0], step, n: t.length } : t, cols };
  }

  function decodeGrid(w) {
    const t = Array.isArray(w.t) ? w.t.map(Number) : Array.from({ length: w.t.n }, (_, i) => w.t.t0 + i * w.t.step);
    const cols = {};
    for (const [k, runs] of Object.entries(w.cols || {})) {
      const v = [];
      for (const [x, n] of runs) for (let i = 0; i < n; i++) v.push(x);
      if (v.length !== t.length) throw new Error(`sql_grid: column ${k} has ${v.length} values for ${t.length} times`);
      cols[k] = v;
    }
    return { t, cols };
  }

  // results: runtime / mech are Maps (key -> Map(weekStart -> row) / key -> hours per bin); JSON carries entries
  function encodeResult(kind, r) {
    if (kind === "runtime") return [...r].map(([k, m]) => [k, [...m]]);
    if (kind === "mech") return [...r];
    return r;
  }
  function decodeResult(kind, r) {
    if (kind === "runtime") return new Map(r.map(([k, e]) => [k, new Map(e)]));
    if (kind === "mech") return new Map(r);
    return r;
  }

  /** A client calling `call(args) -> hook answer`; the answer's `result` is decoded back to the in-process shapes. */
  function makeClient(call) {
    const run = async (kind, g, specs) => {
      const args = { tool: "sql_grid", kind, grid: JSON.stringify(encodeGrid(g)) };
      if (specs) args.specs = JSON.stringify(kind === "runtime" ? plainRuntimeSpecs(Array.from(g.t), specs) : specs);
      const ans = await call(args);
      if (!ans || !ans.ok) throw new Error(`SQL analytics (${kind}) failed: ${(ans && ans.error) || "no answer"}`);
      return decodeResult(kind, ans.result);
    };
    return {
      runtime: (g, specs) => run("runtime", g, specs),
      mech: (g, specs) => run("mech", g, specs),
      econ: (g) => run("econ", g),
      bas: (g) => run("bas", g),
    };
  }

  /** The browser transport: start the analytics hook, poll its runs, return its JSON answer (as tuning.js does). */
  function hookCall(args) {
    const appId = ((typeof location !== "undefined" && location.pathname.match(/\/apps\/static\/([^/]+)\//)) || [])[1] || "open-fdd";
    const base = `/api/v1/apps/${appId}/hooks/analytics`;
    return (async () => {
      const { pid } = await root.api(base, args);
      const deadline = Date.now() + 120e3;
      while (Date.now() < deadline) {
        await new Promise((ok) => setTimeout(ok, 500));
        const runs = (await root.api(`${base}/runs?page_size=10&include_results=true&include_logs=true`)).runs || [];
        const run = runs.find((r) => r.pid === pid || (r.run && r.run.pid === pid));
        if (!run) continue;
        const state = String(run.state || run.status || "").toUpperCase();
        if (/RUNNING|PENDING|ENQUEUED|SCHEDULED/.test(state)) continue;
        const events = Object.values(run.results || {}).flatMap((x) => (x && x.events) || []);
        const last = [...events].reverse().find((e) => e && typeof e.message === "string" && e.message.trim().startsWith("{"));
        if (!last) throw new Error(`analytics hook ended ${state} without an answer`);
        return JSON.parse(last.message);
      }
      throw new Error("analytics hook still running; try again");
    })();
  }

  const api = { plainRuntimeSpecs, encodeGrid, decodeGrid, encodeResult, decodeResult, makeClient, hookCall };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    root.ofddSqlAnalyticsWire = api;
    if (!root.ofddSqlAnalytics && typeof root.api === "function") root.ofddSqlAnalytics = makeClient(hookCall);
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
