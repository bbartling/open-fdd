// Same evaluation path as nf-app/hooks/sparql.js: sparqlCheckQuery, sparqlLoadStore, store.query JSON.
// Oxigraph is the npm package in nf-app, the same module the hook loads.
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const requireApp = createRequire(new URL("../../../nf-app/package.json", import.meta.url));
const lib = require("../../../nf-app/static/sparql.js");
const ox = requireApp("oxigraph");

const spec = JSON.parse(readFileSync(process.argv[2], "utf8"));
const turtle = readFileSync(spec.turtle, "utf8");
const examples = lib.sparqlExamples(turtle);
const queries = { ...spec.queries };
if (spec.includeExamples) {
  for (const item of examples) queries[item.id] = item.query;
}
lib.sparqlCheckQuery(Object.values(queries)[0]);
const store = lib.sparqlLoadStore(ox, turtle);
const out = {};
for (const [name, query] of Object.entries(queries)) {
  const form = lib.sparqlCheckQuery(query).form;
  if (form === "ASK") {
    out[name] = { kind: "ask", value: store.query(query) === true };
    continue;
  }
  const parsed = JSON.parse(store.query(query, { results_format: "json" }));
  const vars = (parsed.head && parsed.head.vars) || [];
  const bindings = ((parsed.results && parsed.results.bindings) || []).map((row) => {
    const cell = {};
    for (const name of vars) {
      const term = row[name];
      if (!term) {
        cell[name] = null;
      } else if (term.type === "uri") {
        cell[name] = { type: "uri", value: term.value };
      } else if (term.type === "bnode") {
        cell[name] = { type: "bnode", value: term.value };
      } else {
        cell[name] = {
          type: "literal",
          value: term.value,
          datatype: term.datatype || "",
          lang: term["xml:lang"] || "",
        };
      }
    }
    return cell;
  });
  out[name] = { kind: "select", vars, bindings };
}
writeFileSync(process.argv[3], JSON.stringify({ queries, results: out }));
