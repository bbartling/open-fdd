#!/usr/bin/env node
/**
 * Regenerate frontend/web/public/plotly.css from the vendored plotly.min.js.
 * Run after upgrading public/plotly.min.js (needs Playwright chromium).
 */
import { chromium } from "playwright";
import { createServer } from "http";
import { readFileSync, writeFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = join(here, "../../frontend/web");
const plotlyJs = readFileSync(join(webRoot, "public/plotly.min.js"), "utf8");
const outPath = join(webRoot, "public/plotly.css");

const html = `<!DOCTYPE html><html><body><div id="gd" style="width:600px;height:400px"></div>
<script>${plotlyJs}</script><script>
(async()=>{
  await Plotly.newPlot('gd',[
    {x:[1,2,3],y:[2,1,3],type:'scatter',mode:'markers+lines'},
    {x:[1,2,3],y:[3,2,1],type:'bar'},
  ],{width:600,height:400,title:'export'},{displayModeBar:true,displaylogo:false});
  window.ok=true;
})();
</script></body></html>`;

const server = createServer((_, res) => {
  res.end(html);
});
server.listen(0);
const port = server.address().port;

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(`http://127.0.0.1:${port}/`);
await page.waitForFunction(() => window.ok, { timeout: 120_000 });
const css = await page.evaluate(() => {
  let out = "";
  for (const st of document.querySelectorAll("style")) {
    const sheet = st.sheet;
    if (!sheet) continue;
    for (const rule of sheet.cssRules) {
      out += `${rule.cssText}\n`;
    }
  }
  return out;
});
writeFileSync(outPath, css, "utf8");
console.log(`Wrote ${outPath} (${css.length} bytes)`);
server.close();
await browser.close();
