// Run open-fdd's own nf.js + model.js in Node on a fixture model, write the Turtle it makes.
// usage: node gen_ttl.js <fixture.json> <out.ttl> [static dir] [nf base url]
// Default static dir = ../../nf-app/static. No live NF needed.
const fs = require("fs"), vm = require("vm"), path = require("path");
const [fixture, out, dir = path.join(__dirname, "..", "..", "nf-app", "static"), nfBase = "http://nf.example.test"] = process.argv.slice(2);
const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
for (const f of ["paging.js", "nf.js", "model.js"]) vm.runInContext(fs.readFileSync(path.join(dir, f), "utf8"), ctx, { filename: f });
ctx.records = JSON.parse(fs.readFileSync(fixture, "utf8")).records;
const r = vm.runInContext(`(() => {
  const of = (t) => records.filter((x) => x.pointType === t);
  const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: of("DEVICE"), points: of("POINT").map(toPoint) };
  return modelToTurtle(model, "urn:test:", { nfBase: ${JSON.stringify(nfBase)} });
})()`, ctx);
fs.writeFileSync(out, r.turtle);
console.log(JSON.stringify({ nonStandard: Array.from(r.nonStandard), bytes: r.turtle.length }));
