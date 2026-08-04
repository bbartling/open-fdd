const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const evid = process.env.EVID || '/openfdd/reports/parity';
(async () => {
  const browser = await chromium.launch({ headless: true });
  for (const [w, h] of [[1440, 900], [1280, 800]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, locale: 'en-US', timezoneId: 'UTC' });
    const page = await ctx.newPage();
    const cons = [];
    page.on('pageerror', e => cons.push({ type: 'pageerror', message: String(e) }));
    page.on('console', m => { if (m.type() === 'error') cons.push({ type: 'console', message: m.text() }); });
    try {
      await page.goto('http://127.0.0.1:3000/', { waitUntil: 'networkidle', timeout: 60000 });
    } catch (e) {
      cons.push({ type: 'nav', message: String(e) });
    }
    await page.waitForTimeout(2000);
    const dir = path.join(evid, 'react', `${w}x${h}`);
    fs.mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: path.join(dir, 'overview__initial.png'), fullPage: false });
    fs.writeFileSync(path.join(evid, 'console', `react_${w}x${h}.json`), JSON.stringify(cons, null, 2));
    const box = await page.evaluate(() => ({
      title: document.title,
      bodyBg: getComputedStyle(document.body).backgroundColor,
      font: getComputedStyle(document.body).fontFamily,
      url: location.href,
      w: innerWidth,
      h: innerHeight,
    }));
    fs.mkdirSync(path.join(evid, 'measurements'), { recursive: true });
    fs.writeFileSync(path.join(evid, 'measurements', `react_${w}x${h}_overview.json`), JSON.stringify(box, null, 2));
    await ctx.close();
  }
  await browser.close();
  console.log('react screenshots ok');
})().catch(e => { console.error(e); process.exit(1); });
