// Runs the NF app's RCx run-hours maths (nf-app/static/rcx-overview.js, rcxOverviewMath) on a JSON dataset from stdin and prints the
// results as JSON. Used by tests/parity/test_rcx_analytics_parity.py to compare pandas (open_fdd.analytics.core) with the app.
//   stdin : { "equips": { "<id>": { "t": [ms...], "fan": [..], "comp": [..], "oat": [..], "web": [..] } } }
//   stdout: { "<id>": { "weekly": { "<weekStartMs>": { "hours", "oat", "partial" } }, "mech": { "labels": [...], "hours": [...] } } }
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../../nf-app/static/", import.meta.url);
const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa, localStorage: { getItem: () => "si" } });
ctx.FAULT_LANE = { lineStyle: { color: "red" }, areaStyle: { color: "red" } };
ctx.pickWindow = () => 300;
ctx.ofddChart = () => ({}); ctx.ofddRender = () => {}; ctx.fetchSeries = async () => new Map();
for (const f of ["units.js", "paging.js", "nf.js", "model.js", "fdd.js", "schedule.js", "charts.js", "rcx.js", "rcx-overview.js"]) {
  vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
}
const M = vm.runInContext("rcxOverviewMath", ctx);
const input = JSON.parse(readFileSync(0, "utf8"));
const out = {};
for (const [id, e] of Object.entries(input.equips)) {
  const weekly = M.weeklyRuntime(e.t, e.fan, { duty: false, gapMaxSec: 3600, oat: e.oat });
  out[id] = {
    weekly: Object.fromEntries([...weekly].map(([k, w]) => [String(k), { hours: w.hours, oat: w.oat, partial: w.partial }])),
    // the app's policy: weekly runtime averages the equip's own oa_t; the cooling bins prefer weather (web) outdoor air, else oa_t
    mech: M.mechBins(e.t, e.comp, e.web.some((v) => v != null) ? e.web : e.oat, { duty: false, gapMaxSec: 3600 }),
  };
}
process.stdout.write(JSON.stringify(out));
