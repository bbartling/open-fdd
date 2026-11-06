// SPARQL over the site's Haystack model (Turtle from modelToTurtle), run by Oxigraph (WASM).
//
// Browser: classic script. On load it appends a "SPARQL" panel to #tab-model (no index.html
// markup). Oxigraph is loaded lazily, only when the panel is first used, from
// vendor/oxigraph/web.js + web_bg.wasm (needs 'wasm-unsafe-eval' in the CSP script-src).
// The store is rebuilt whenever the app's Turtle (global `rdf`, set by app.js each time the
// model reloads) changes.
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
`SELECT ?equip ?kind (COUNT(?p) AS ?points) WHERE {
  ?e a phIoT:equip ; rdfs:label ?equip .
  OPTIONAL { ?p phIoT:equipRef ?e ; a phIoT:point . OPTIONAL { ?p ph:kind ?k } }
  BIND(COALESCE(?k, "(no points)") AS ?kind)
}
GROUP BY ?equip ?kind
ORDER BY ?equip ?kind` },
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

/**
 * Run one query on an Oxigraph Store. Returns
 *   {kind:"select", vars, rows:[[text|null,...]], total, truncated}
 *   {kind:"ask", value}
 *   {kind:"graph", turtle, total, truncated}   (CONSTRUCT / DESCRIBE)
 * Throws on a parse or evaluation error (message = Oxigraph's). Oxigraph evaluates synchronously
 * and materialises the whole result, so `cap` limits what is returned/shown, not the work done:
 * put LIMIT in the query for anything big.
 */
function sparqlExec(store, query, cap = SPARQL_ROW_CAP) {
  const res = store.query(query);
  if (typeof res === "boolean") return { kind: "ask", value: res };
  if (typeof res === "string") return { kind: "graph", turtle: res, total: null, truncated: false };
  let vars = null;
  if (res.length === 0 || res[0] instanceof Map) {
    try { vars = JSON.parse(store.query(query, { results_format: "json" })).head.vars; } catch (e) { vars = null; }
  }
  if (vars) {
    const rows = res.slice(0, cap).map((m) => vars.map((v) => (m.has(v) ? sparqlTermText(m.get(v)) : null)));
    return { kind: "select", vars, rows, total: res.length, truncated: res.length > cap };
  }
  const quads = res.slice(0, cap);
  const turtle = quads.length ? new store.constructor(quads).dump({ format: "text/turtle", from_graph_name: quads[0].graph }) : "";
  const triples = quads.map((q) => [sparqlTermText(q.subject), sparqlTermText(q.predicate), sparqlTermText(q.object)]);
  return { kind: "graph", turtle, triples, total: res.length, truncated: res.length > cap };
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
  module.exports = { SPARQL_ROW_CAP, sparqlPrefixes, sparqlExamples, sparqlExec, sparqlToCsv, sparqlCsvField, sparqlTermText };
}

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
    const s = new mod.Store();
    s.load(ttl, { format: "text/turtle" });
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

  async function runQuery() {
    showError(""); csv.disabled = true; run.disabled = true;
    stat.textContent = "running…";
    try {
      const s = await getStore();
      const t0 = performance.now();
      const r = sparqlExec(s, ta.value);
      const ms = Math.round(performance.now() - t0);
      last = r; render(r);
      const n = r.kind === "ask" ? "ASK" : `${r.total ?? "?"} ${r.kind === "select" ? "rows" : "triples"}`;
      stat.textContent = `${ms} ms · ${n}${r.truncated ? ` (showing first ${SPARQL_ROW_CAP})` : ""}`;
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
