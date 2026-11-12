// Peak memory + time of one SQL engine running every rule: 1 equipment x 7 days x 5 min.
//   node scripts/nf/measure_engines.mjs [sqlite|pglite] [equipments] [days]
// Run one engine per process (RSS is per process). Baseline = RSS right after startup, before the engine loads.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const kind = process.argv[2] || "sqlite";
const equipments = Number(process.argv[3] || 1);
const days = Number(process.argv[4] || 7);
const mb = (b) => (b / 1048576).toFixed(1);
const packFile = kind === "pglite" ? "pack-postgres.json" : "pack-sqlite.json";
const pack = JSON.parse(readFileSync(new URL(`../../nf-app/rules/${packFile}`, import.meta.url), "utf8"));
const { createEngine } = require("../../nf-app/hooks/lib/engines.js");
const { buildDataset } = require("../../nf-app/tests/fixtures/synthetic_dataset.js");

let peak = 0;
const sample = () => { peak = Math.max(peak, process.memoryUsage().rss); };
const timer = setInterval(sample, 20);

const baseline = process.memoryUsage().rss;
const input = buildDataset(pack, { equipments, days });
sample();
const afterData = process.memoryUsage().rss;
const t0 = Date.now();
const eng = await createEngine({ kind, pack });
sample();
await eng.load(input);
const tLoad = Date.now();
let ran = 0, failed = 0;
for (const rid of Object.keys(pack.rules)) {
  try { await eng.query(rid); ran++; } catch { failed++; }
  sample();
}
const tDone = Date.now();
await eng.close();
clearInterval(timer);
sample();
console.log(JSON.stringify({
  engine: kind, equipments, days, history_rows: input.history.length, rules_ran: ran, rules_failed: failed,
  rss_mb: { baseline_node: +mb(baseline), after_dataset: +mb(afterData), peak: +mb(peak), peak_os_reported: +mb(process.resourceUsage().maxRSS * 1024) },
  engine_overhead_mb: +mb(peak - afterData),
  seconds: { init_and_load: (tLoad - t0) / 1000, all_rules: (tDone - tLoad) / 1000 },
}, null, 1));
