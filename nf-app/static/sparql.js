// SPARQL over the site's Haystack model (Turtle from modelToTurtle), run by Oxigraph (WASM).
//
// Browser: classic script. On load it appends a "SPARQL" panel to #tab-model (no index.html
// markup). Oxigraph is loaded lazily, only when the panel is first used, from
// vendor/oxigraph/web.js + web_bg.wasm (needs 'wasm-unsafe-eval' in the CSP script-src).
// The store is rebuilt whenever the app's Turtle (global `rdf`, set by app.js each time the
// model reloads) changes. Queries run in a Worker (this same file, see "worker side") that is
// terminated after a timeout; without Worker support they run on the main thread, uninterruptible.
// Read-only: only SELECT / ASK / CONSTRUCT / DESCRIBE, no SERVICE (sparqlCheckQuery).
//
// Node: `require("./sparql.js")` gives the pure helpers the hook and the tests use
// (sparqlExec, sparqlToCsv, sparqlExamples, ...). Nothing here knows a site, equip or point.
"use strict";

const SPARQL_ROW_CAP = 5000;
const SPARQL_SCRIPT_SRC = typeof document !== "undefined" && document.currentScript ? /** @type {HTMLScriptElement} */ (document.currentScript).src : "";

// ---- pure helpers (browser + hook + tests) -------------------------------------------------
/** "PREFIX x: <iri>" lines, copied from the @prefix lines of the generated Turtle. */
function sparqlPrefixes(turtle) {
  const out = [];
  for (const m of String(turtle).matchAll(/^@prefix\s+([A-Za-z0-9_-]*):\s*<([^>]*)>\s*\./gm)) out.push(`PREFIX ${m[1]}: <${m[2]}>`);
  return out.join("\n");
}

/** Example queries. Prefixes come from the Turtle, so they follow whatever base the app used. */
function sparqlExamples(turtle) {
  const P = sparqlPrefixes(turtle) + "\n\n";
  return [
    { id: "ts-ids", label: "Points of each equip with time-series id + history URL (default)", query: P +
`SELECT ?equip ?point ?tsId ?history WHERE {
  ?p a phIoT:point ; rdfs:label ?point ; phIoT:equipRef ?e ;
     ref:hasExternalReference ?r .
  ?e rdfs:label ?equip .
  ?r a ref:TimeseriesReference ; ref:hasTimeseriesId ?tsId .
  OPTIONAL { ?r schema:url ?history }
}
ORDER BY ?equip ?point` },
    { id: "equips-kinds", label: "Equips and the kinds of points they own", query: P +
`SELECT ?site ?equip ?kind (COUNT(?p) AS ?points) WHERE {
  ?e a phIoT:equip ; rdfs:label ?equip .
  OPTIONAL { ?e phIoT:siteRef ?s . ?s rdfs:label ?siteLabel }
  OPTIONAL { ?p phIoT:equipRef ?e ; a phIoT:point . OPTIONAL { ?p ph:kind ?k } }
  BIND(COALESCE(?siteLabel, "") AS ?site)
  BIND(COALESCE(?k, "(no points)") AS ?kind)
}
GROUP BY ?e ?site ?equip ?kind
ORDER BY ?site ?equip ?kind` },
    { id: "faults", label: "Fault result points (markers fdd + fault, with ruleRef if exported)", query: P +
`SELECT ?point ?equip ?rule WHERE {
  ?p a phIoT:point ; rdfs:label ?point ; ph:hasTag local:fdd, local:fault .
  OPTIONAL { ?p phIoT:equipRef ?e . ?e rdfs:label ?equip }
  OPTIONAL { ?p local:ruleRef ?rule }
}
ORDER BY ?equip ?point` },
    { id: "no-equip", label: "Points with no equipRef", query: P +
`SELECT ?point ?weatherStation ?device WHERE {
  ?p a phIoT:point ; rdfs:label ?point .
  FILTER NOT EXISTS { ?p phIoT:equipRef ?any }
  OPTIONAL { ?p phIoT:weatherStationRef ?ws . ?ws rdfs:label ?weatherStation }
  OPTIONAL { ?p phIct:deviceRef ?d . ?d rdfs:label ?device }
}
ORDER BY ?point` },
    { id: "ts-refs", label: "External time-series references per point", query: P +
`SELECT ?point ?tsId ?store ?storeLabel WHERE {
  ?p a phIoT:point ; rdfs:label ?point ; ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?tsId ; ref:storedAt ?store .
  OPTIONAL { ?store rdfs:label ?storeLabel }
}
ORDER BY ?point ?store` },
    { id: "counts", label: "Counts by tag (the model has no class attribute yet)", query: P +
`SELECT ?tag (COUNT(DISTINCT ?p) AS ?points) WHERE {
  ?p a phIoT:point ; ph:hasTag ?tag .
}
GROUP BY ?tag
ORDER BY DESC(?points) ?tag` },
  ];
}

const sparqlTermText = (t) => {
  if (t == null) return "";
  if (t.termType === "NamedNode" || t.termType === "Literal") return t.value;
  if (t.termType === "BlankNode") return "_:" + t.value;
  return String(t);
};

// ---- read-only policy ----------------------------------------------------------------------
// Only SELECT, ASK, CONSTRUCT and DESCRIBE run. UPDATE operations (INSERT, DELETE, LOAD, CLEAR, DROP,
// CREATE, COPY, MOVE, ADD, WITH) and SERVICE (remote federation: the query would make the NF box or the
// browser fetch an arbitrary URL) are refused before the engine sees the text. The check works on the
// query with comments, string literals and <IRIs> blanked out, so those words inside data are fine.
const SPARQL_QUERY_CAP = 20000;
const SPARQL_MAX_TRIPLES = 500000;       // default model size limit, see sparqlLoadStore
const SPARQL_FORMS = ["SELECT", "ASK", "CONSTRUCT", "DESCRIBE"];
const SPARQL_BLANKABLE = /<[^<>"{}|^`\\\x00-\x20]*>|"""(?:[^"\\]|\\[\s\S]|"(?!""))*"""|'''(?:[^'\\]|\\[\s\S]|'(?!''))*'''|"(?:[^"\\\n\r]|\\.)*"|'(?:[^'\\\n\r]|\\.)*'|#[^\n\r]*/g;
const SPARQL_PROLOGUE = /^\s*(?:PREFIX\s+[^\s:]*:\s*<>|BASE\s*<>)/i;
const SPARQL_DENIED_ANYWHERE = /(?<![?$\w:-])(SERVICE|INSERT|DELETE|LOAD|CLEAR|DROP)(?![\w:-])/i;

/** SPARQL allows \uXXXX / \UXXXXXXXX escapes anywhere in the text: look at it decoded as well. */
function sparqlDecodeEscapes(q) {
  return q.replace(/\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})/g, (m, a, b) => {
    try { return String.fromCodePoint(parseInt(a || b, 16)); } catch (e) { return m; }
  });
}

function sparqlFormOf(text) {
  let t = text.replace(SPARQL_BLANKABLE, (m) => (m[0] === "<" ? "<>" : " "));   // IRIs keep their brackets (PREFIX/BASE), the rest goes
  for (let i = 0; i < 1000 && SPARQL_PROLOGUE.test(t); i++) t = t.replace(SPARQL_PROLOGUE, "");
  const m = /^\s*([A-Za-z]+)/.exec(t);
  return { form: m ? m[1].toUpperCase() : "", blanked: t };
}

/**
 * Policy check. Returns {form} ("SELECT" | "ASK" | "CONSTRUCT" | "DESCRIBE") or throws Error with a
 * message that says what is refused. Does not parse SPARQL fully: the engine still reports syntax errors.
 */
function sparqlCheckQuery(query) {
  if (typeof query !== "string" || !query.trim()) throw new Error("args.query is required");
  if (query.length > SPARQL_QUERY_CAP) throw new Error(`query longer than ${SPARQL_QUERY_CAP} characters`);
  let form = "";
  for (const text of new Set([query, sparqlDecodeEscapes(query)])) {
    const r = sparqlFormOf(text);
    const bad = SPARQL_DENIED_ANYWHERE.exec(r.blanked);
    if (bad) {
      const w = bad[1].toUpperCase();
      throw new Error(w === "SERVICE"
        ? "SERVICE (federated queries to other endpoints) is not allowed"
        : `${w}: updates are not allowed, SPARQL here is read-only`);
    }
    if (!SPARQL_FORMS.includes(r.form)) {
      throw new Error(`only SELECT, ASK, CONSTRUCT and DESCRIBE are allowed${r.form ? ` (got ${r.form})` : ""}: SPARQL here is read-only`);
    }
    form = form || r.form;
  }
  return { form };
}

/**
 * New Store loaded from the Turtle, refusing a model over `maxTriples` before any query runs.
 * (Parsing is the one step this cannot bound: a huge Turtle is still parsed once.)
 */
function sparqlLoadStore(ox, turtle, maxTriples = SPARQL_MAX_TRIPLES) {
  const store = new ox.Store();
  store.load(turtle, { format: "text/turtle" });
  const n = typeof store.size === "number" ? store.size : store.length;
  if (Number.isFinite(maxTriples) && n > maxTriples) {
    throw new Error(`model has ${n} triples, over the limit of ${maxTriples}: SPARQL is refused for models this large`);
  }
  return store;
}

// SPARQL JSON results term -> text (same text sparqlTermText gives for the Term objects).
const sparqlJsonTermText = (t) => (t == null ? null : t.type === "bnode" ? "_:" + t.value : String(t.value));

/**
 * Run one query on an Oxigraph Store, exactly once. Returns
 *   {kind:"select", vars, rows:[[text|null,...]], total, truncated}
 *   {kind:"ask", value}
 *   {kind:"graph", turtle, triples, total, truncated}   (CONSTRUCT / DESCRIBE)
 * Throws on a policy violation, parse error or evaluation error (message = Oxigraph's).
 * Limits: the query text is capped (SPARQL_QUERY_CAP) and so are the returned rows (`cap`). Oxigraph
 * evaluates synchronously and materialises the whole result, so `cap` limits what is returned, not the
 * work done, and a running evaluation cannot be interrupted from inside the same thread: put LIMIT in
 * the query, or run it in a Worker that can be terminated (the browser panel does).
 */
function sparqlExec(store, query, cap = SPARQL_ROW_CAP) {
  const { form } = sparqlCheckQuery(query);
  if (form === "ASK") return { kind: "ask", value: store.query(query) === true };
  if (form === "SELECT") {
    // One evaluation: the JSON result carries the variable names even when there are no rows.
    const j = JSON.parse(store.query(query, { results_format: "json" }));
    const vars = (j.head && j.head.vars) || [];
    const all = (j.results && j.results.bindings) || [];
    const rows = all.slice(0, cap).map((b) => vars.map((v) => sparqlJsonTermText(b[v])));
    return { kind: "select", vars, rows, total: all.length, truncated: all.length > cap };
  }
  const res = store.query(query);
  if (typeof res === "string") return { kind: "graph", turtle: res, total: null, truncated: false };
  const quads = res.slice(0, cap);
  const turtle = quads.length ? new store.constructor(quads).dump({ format: "text/turtle", from_graph_name: quads[0].graph }) : "";
  const triples = quads.map((q) => [sparqlTermText(q.subject), sparqlTermText(q.predicate), sparqlTermText(q.object)]);
  return { kind: "graph", turtle, triples, total: res.length, truncated: res.length > cap };
}

// ---- Web Worker client (browser panel; testable with a fake Worker) --------------------------
/**
 * Runs queries in a Worker so a runaway one can be stopped: on timeout the Worker is terminated
 * (the only way to interrupt a synchronous wasm evaluation) and the next run starts a fresh one.
 * `spawn()` returns a Worker-like {postMessage, terminate, onmessage, onerror}. The Turtle is sent
 * only when it changed since the last message this Worker saw. A rejected promise has `.timedOut` or
 * `.workerUnavailable` set when that is the reason (the caller may then fall back to the main thread).
 */
function sparqlWorkerClient(spawn, timeoutMs = 20000) {
  let worker = null, sentTurtle = null, seq = 0, pending = null;
  const drop = () => { if (worker) { try { worker.terminate(); } catch (e) { /* already gone */ } } worker = null; sentTurtle = null; };
  const fail = (err) => { const p = pending; pending = null; if (p) { clearTimeout(p.timer); p.reject(err); } };
  function run(turtle, query, cap) {
    if (pending) return Promise.reject(new Error("a query is already running"));
    return new Promise((resolve, reject) => {
      try {
        if (!worker) {
          worker = spawn();
          worker.onmessage = (ev) => {
            const d = ev.data || {};
            if (!pending || d.id !== pending.id) return;
            const p = pending; pending = null; clearTimeout(p.timer);
            if (d.ok) p.resolve(d.result); else {
              sentTurtle = null;
              const e = Object.assign(new Error(d.error || "query failed"), d.unavailable ? { workerUnavailable: true } : {});
              if (d.unavailable) drop();
              p.reject(e);
            }
          };
          worker.onerror = (ev) => {
            const e = Object.assign(new Error((ev && ev.message) || "the SPARQL worker could not start"), { workerUnavailable: true });
            drop(); fail(e);
          };
        }
      } catch (e) { drop(); reject(Object.assign(new Error(String((e && e.message) || e)), { workerUnavailable: true })); return; }
      const id = ++seq;
      const timer = setTimeout(() => {
        drop();
        fail(Object.assign(new Error(`query stopped after ${Math.round(timeoutMs / 1000)} s (timeout); the worker was terminated, add LIMIT or narrow the pattern`), { timedOut: true }));
      }, timeoutMs);
      pending = { id, resolve, reject, timer };
      const msg = { id, query, cap };
      if (sentTurtle !== turtle) { msg.turtle = turtle; sentTurtle = turtle; }
      worker.postMessage(msg);
    });
  }
  return { run, dispose: () => { fail(new Error("cancelled")); drop(); } };
}

/** RFC 4180 CSV: quote fields holding comma, quote, CR or LF; double embedded quotes. */
function sparqlCsvField(v) {
  const s = v == null ? "" : String(v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function sparqlToCsv(r) {
  const line = (a) => a.map(sparqlCsvField).join(",");
  if (r.kind === "ask") return line(["result"]) + "\r\n" + line([r.value]) + "\r\n";
  if (r.kind === "select") return [line(r.vars), ...r.rows.map(line)].join("\r\n") + "\r\n";
  // graph: one row per triple.
  if (r.triples) return [line(["subject", "predicate", "object"]), ...r.triples.map(line)].join("\r\n") + "\r\n";
  return line(["turtle"]) + "\r\n" + line([r.turtle]) + "\r\n";
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    SPARQL_ROW_CAP, SPARQL_QUERY_CAP, SPARQL_MAX_TRIPLES, sparqlPrefixes, sparqlExamples, sparqlExec, sparqlToCsv, sparqlCsvField,
    sparqlTermText, sparqlCheckQuery, sparqlLoadStore, sparqlWorkerClient,
  };
}

// ---- worker side ---------------------------------------------------------------------------
// The browser panel starts this same file as `new Worker("sparql.js")` (classic worker, same origin,
// so it passes worker-src 'self') to run queries where they can be terminated on timeout.
// Protocol: {id, query, cap, turtle?} in; {id, ok:true, result} | {id, ok:false, error, unavailable?} out.
// `unavailable` = Oxigraph could not be loaded in the worker (e.g. no wasm there): the page falls back.
(function sparqlWorkerMain() {
  const G = /** @type {any} */ (globalThis);
  if (typeof document !== "undefined" || typeof G.WorkerGlobalScope === "undefined" || !(G instanceof G.WorkerGlobalScope)) return;
  let store = null, loading = null;
  const boot = () => loading || (loading = (async () => {
    const base = new URL("vendor/oxigraph/", G.location.href);
    const mod = await import(new URL("web.js", base).href);
    await mod.default({ module_or_path: new URL("web_bg.wasm", base) });
    return mod;
  })());
  G.onmessage = async (ev) => {
    const { id, query, cap, turtle } = ev.data || {};
    let mod;
    try { mod = await boot(); } catch (e) { loading = null; G.postMessage({ id, ok: false, unavailable: true, error: String((e && e.message) || e) }); return; }
    try {
      if (typeof turtle === "string") { store = null; store = sparqlLoadStore(mod, turtle); }
      if (!store) throw new Error("no model loaded in the worker");
      G.postMessage({ id, ok: true, result: sparqlExec(store, query, cap) });
    } catch (e) { G.postMessage({ id, ok: false, error: String((e && e.message) || e) }); }
  };
})();

// ---- browser panel ------------------------------------------------------------------------
if (typeof document !== "undefined") (function mountSparqlPanel() {
  let ox = null, oxLoading = null, store = null, storeTtl = null, last = null;

  const el = (tag, props = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "style") Object.assign(n.style, v);        // CSSOM, allowed under style-src 'self'
      else if (k in n) n[k] = v;
      else n.setAttribute(k, v);
    }
    n.append(...kids);
    return n;
  };

  const turtleNow = () => {
    if (typeof rdf !== "undefined" && rdf && rdf.turtle) return rdf.turtle;
    if (typeof model !== "undefined" && model && typeof modelToTurtle === "function") {
      return modelToTurtle(model, `urn:nf:${location.host}:`).turtle;
    }
    return null;
  };

  async function loadOxigraph() {
    if (ox) return ox;
    if (!oxLoading) {
      oxLoading = (async () => {
        const base = new URL("vendor/oxigraph/", SPARQL_SCRIPT_SRC || location.href);
        const mod = await import(new URL("web.js", base).href);
        await mod.default({ module_or_path: new URL("web_bg.wasm", base) });
        ox = mod;
        return mod;
      })().catch((e) => { oxLoading = null; throw e; });
    }
    return oxLoading;
  }

  async function getStore() {
    const ttl = turtleNow();
    if (!ttl) throw new Error("The model is not loaded yet.");
    const mod = await loadOxigraph();
    if (store && storeTtl === ttl) return store;
    const s = sparqlLoadStore(mod, ttl);
    store = s; storeTtl = ttl;
    return s;
  }

  const ta = el("textarea", { rows: 12, spellcheck: false, style: { width: "100%", fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: "12px", boxSizing: "border-box" } });
  const pick = el("select", { title: "Example queries" });
  const run = el("button", { className: "btn primary", textContent: "Run" });
  const csv = el("button", { className: "btn", textContent: "Download results as CSV", disabled: true });
  const stat = el("span", { className: "hint" });
  const err = el("pre", { style: { color: "var(--hot)", whiteSpace: "pre-wrap", margin: "8px 0", display: "none" } });
  const out = el("div", { style: { overflow: "auto", maxHeight: "420px", marginTop: "8px" } });
  const panel = el("section", { className: "panel", id: "sparqlPanel" },
    el("h2", {}, "SPARQL ",
      el("span", { className: "hint" }, "query the Haystack model as RDF (Oxigraph in your browser; loaded on first Run). "
        + "Same engine as the sparql hook: POST /api/v1/apps/open-fdd/hooks/sparql")),
    el("div", { className: "actions", style: { marginBottom: "8px", display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" } }, pick, run, csv, stat),
    ta, err, out);

  let examples = [];
  const refreshExamples = () => {
    const ttl = turtleNow();
    if (!ttl) return;
    const was = pick.value;
    examples = sparqlExamples(ttl);
    pick.replaceChildren(...examples.map((x) => el("option", { value: x.id, textContent: x.label })));
    if (was) pick.value = was;
  };
  const loadExample = () => { const x = examples.find((e) => e.id === pick.value); if (x) ta.value = x.query; };
  pick.onchange = loadExample;

  const showError = (m) => { err.textContent = m; err.style.display = m ? "block" : "none"; };

  function render(r) {
    out.replaceChildren();
    if (r.kind === "ask") { out.append(el("p", {}, el("strong", {}, String(r.value)))); return; }
    if (r.kind === "graph") { out.append(el("pre", { textContent: r.turtle || "(empty graph)", style: { fontSize: "12px", whiteSpace: "pre-wrap" } })); return; }
    const head = el("tr", {}, ...r.vars.map((v) => el("th", { textContent: "?" + v })));
    const body = r.rows.map((row) => el("tr", {}, ...row.map((c) => el("td", { textContent: c == null ? "" : c }))));
    out.append(el("table", { className: "bac" }, el("thead", {}, head), el("tbody", {}, ...body)));
  }

  // Queries run in a Worker with a timeout (terminated on expiry). If no Worker can be started the
  // query runs on the main thread, where a runaway evaluation cannot be interrupted.
  const QUERY_TIMEOUT_MS = 20000;
  let client = null, workerBroken = typeof Worker === "undefined" || !SPARQL_SCRIPT_SRC;
  async function execQuery(query) {
    const ttl = turtleNow();
    if (!ttl) throw new Error("The model is not loaded yet.");
    sparqlCheckQuery(query);                       // refuse updates / SERVICE before any work
    if (!workerBroken) {
      try {
        client = client || sparqlWorkerClient(() => new Worker(SPARQL_SCRIPT_SRC), QUERY_TIMEOUT_MS);
        return { r: await client.run(ttl, query, SPARQL_ROW_CAP), where: "worker" };
      } catch (e) {
        if (!e.workerUnavailable) throw e;
        workerBroken = true; client = null;
      }
    }
    return { r: sparqlExec(await getStore(), query), where: "main thread, no timeout" };
  }

  async function runQuery() {
    showError(""); csv.disabled = true; run.disabled = true;
    stat.textContent = "running…";
    try {
      const t0 = performance.now();
      const { r, where } = await execQuery(ta.value);
      const ms = Math.round(performance.now() - t0);
      last = r; render(r);
      const n = r.kind === "ask" ? "ASK" : `${r.total ?? "?"} ${r.kind === "select" ? "rows" : "triples"}`;
      stat.textContent = `${ms} ms · ${n}${r.truncated ? ` (showing first ${SPARQL_ROW_CAP})` : ""} · ${where}`;
      csv.disabled = false;
    } catch (e) {
      out.replaceChildren(); stat.textContent = "";
      showError(String((e && e.message) || e));
    } finally { run.disabled = false; }
  }
  run.onclick = runQuery;
  ta.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); runQuery(); } });
  csv.onclick = () => {
    if (!last) return;
    const url = URL.createObjectURL(new Blob([sparqlToCsv(last)], { type: "text/csv" }));
    const a = el("a", { href: url, download: "sparql-results.csv" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const host = document.getElementById("tab-model");
  if (!host) return;
  host.append(panel);
  // The model loads after this script runs: fill the examples once the Turtle exists, and
  // again after every reload (cheap: string compare), without loading Oxigraph.
  let seenTtl = null, firstFill = true;
  const sync = () => {
    const ttl = turtleNow();
    if (!ttl || ttl === seenTtl) return;
    seenTtl = ttl; refreshExamples();
    if (firstFill || !ta.value) { loadExample(); firstFill = false; }
  };
  sync();
  setInterval(sync, 1500);
})();
