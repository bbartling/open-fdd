// Full hook path (hooks/sparql.js runSparql, the oxigraph npm package) for tests/test_sparql_engines.py.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hook = require("../../../nf-app/hooks/sparql.js");
const spec = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = {};
for (const [name, query] of Object.entries(spec.queries)) {
  const result = hook.runSparql(spec.turtle, query, "json");
  out[name] = result.rows.map((row) => Object.fromEntries(result.vars.map((variable, i) => [variable, row[i]])));
}
process.stdout.write(JSON.stringify(out));
