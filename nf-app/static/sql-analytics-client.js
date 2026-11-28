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

  // Supported request size: a year of the 300 s fine grid per series, at most 256 series and 2 M cells per request.
  // The hook decodes untrusted JSON: every dimension is checked BEFORE anything is allocated, and a request over
  // budget fails with a clear error (never a silent truncation of real history).
  const LIMITS = { rows: 110000, cols: 256, cells: 2000000 };
  const isCount = (n, max) => Number.isSafeInteger(n) && n >= 0 && n <= max;

  function decodeGrid(w) {
    const bad = (m) => { throw new Error(`sql_grid: ${m}`); };
    if (!w || typeof w !== "object") bad("grid must be an object");
    let n;
    if (Array.isArray(w.t)) {
      if (w.t.length > LIMITS.rows) bad(`${w.t.length} times exceeds the supported ${LIMITS.rows}`);
      n = w.t.length;
    } else if (w.t && typeof w.t === "object") {
      if (!isCount(w.t.n, LIMITS.rows)) bad(`t.n must be an integer 0..${LIMITS.rows}`);
      if (!Number.isFinite(w.t.t0) || !Number.isFinite(w.t.step) || !(w.t.step > 0)) bad("t0 must be finite and step positive");
      n = w.t.n;
    } else bad("t must be an array or {t0, step, n}");
    const entries = Object.entries(w.cols && typeof w.cols === "object" ? w.cols : {});
    if (entries.length > LIMITS.cols) bad(`${entries.length} columns exceeds the supported ${LIMITS.cols}`);
    if (entries.length * n > LIMITS.cells) bad(`${entries.length} x ${n} cells exceeds the supported ${LIMITS.cells}`);
    // validate every run (finite or null value, positive integer count, counts summing to n) before expanding any
    for (const [k, runs] of entries) {
      if (!Array.isArray(runs) || runs.length > n) bad(`column ${k}: runs must be an array of at most ${n} runs`);
      let sum = 0;
      for (const r of runs) {
        if (!Array.isArray(r) || r.length !== 2) bad(`column ${k}: each run is [value, count]`);
        if (r[0] !== null && !Number.isFinite(r[0])) bad(`column ${k}: values must be finite numbers or null`);
        if (!Number.isSafeInteger(r[1]) || r[1] < 1) bad(`column ${k}: run counts must be positive integers`);
        sum += r[1];
        if (sum > n) bad(`column ${k}: runs cover more than ${n} times`);
      }
      if (sum !== n) bad(`column ${k} has ${sum} values for ${n} times`);
    }
    const t = Array.isArray(w.t) ? w.t : Array.from({ length: n }, (_, i) => w.t.t0 + i * w.t.step);
    for (let i = 0; i < n; i++) {
      if (!Number.isFinite(t[i])) bad("times must be finite numbers (epoch ms)");
      if (i && !(t[i] > t[i - 1])) bad("times must be strictly increasing");
    }
    const cols = {};
    for (const [k, runs] of entries) {
      const v = new Array(n);
      let j = 0;
      for (const [x, c] of runs) { v.fill(x, j, j + c); j += c; }
      cols[k] = v;
    }
    return { t: t.slice(), cols };
  }

  /** Plain runtime / mech specs from JSON, bounded like the grid (weeks and occupied intervals are finite ms). */
  function checkSpecs(specs) {
    const bad = (m) => { throw new Error(`sql_grid: ${m}`); };
    if (!Array.isArray(specs) || specs.length > LIMITS.cols) bad(`specs must be an array of at most ${LIMITS.cols}`);
    for (const s of specs) {
      if (!s || typeof s !== "object") bad("each spec is an object");
      for (const k of ["weeks", "occupancy_status"]) {
        const max = LIMITS.rows;
        const a = s[k];
        if (a == null) continue;
        if (!Array.isArray(a) || a.length > max) bad(`spec ${k} must be an array of at most ${max}`);
        for (const x of a.flat()) if (!Number.isFinite(x)) bad(`spec ${k} must hold finite epoch ms`);
      }
    }
    return specs;
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

  const api = { plainRuntimeSpecs, encodeGrid, decodeGrid, checkSpecs, LIMITS, encodeResult, decodeResult, makeClient, hookCall };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    root.ofddSqlAnalyticsWire = api;
    if (!root.ofddSqlAnalytics && typeof root.api === "function") root.ofddSqlAnalytics = makeClient(hookCall);
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
