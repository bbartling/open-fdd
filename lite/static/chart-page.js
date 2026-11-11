// chart.html: one catalog chart per window (charts.js), chosen by the query string.
// Needs nf.js, model.js and charts.js loaded first.

/** @param {string} id @returns {AnyEl} */
const $ = (id) => /** @type {AnyEl} */ (document.getElementById(id));
const q = new URLSearchParams(location.search);
const sel = { id: q.get("c") || CHARTS[0].id, site: q.get("site") || "", equip: q.get("equip") || "",
  hours: Number(q.get("h")) || 0, point: q.get("point") || "" };
let model, ctx, def, chart, rangeState = getChartRangeState("lite.chart"), siteTz = "UTC";

function setLive(ok, txt) {
  $("liveDot").classList.toggle("bad", !ok);
  $("liveTxt").textContent = txt;
}

function syncUrl() {
  const u = new URL(location.href), q = u.searchParams;
  q.set("c", def.id); q.set("site", sel.site); q.set("h", String(sel.hours));
  if (sel.equip) q.set("equip", sel.equip); else q.delete("equip");
  if (def.pick && sel.point) q.set("point", sel.point); else q.delete("point");
  history.replaceState(null, "", u);
}

async function draw() {
  renderRangeControl($("range"), { key: "lite.chart", state: rangeState, siteTz,
    onChange: (next) => { rangeState = next; draw().catch((e) => setLive(false, e.message)); } });
  syncUrl();
  try {
    const hint = await drawChart(chart, def, ctx, rangeState, { point: sel.point });
    if (hint != null) $("hint").textContent = hint;
    setLive(true, `updated ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    setLive(false, e.message);
  }
}

async function main() {
  await initAuth();
  model = await loadModel();
  if (!model.sites.some((s) => idOf(s) === sel.site)) sel.site = idOf(model.sites[0]);
  ctx = pointSets(model, sel.site, sel.equip);
  def = chartDef(sel.id);
  if (!def || !def.applies(ctx)) throw new Error(`chart "${sel.id}" has no matching tagged points here`);
  const site = model.sites.find((s) => idOf(s) === sel.site);
  siteTz = (site?.attrs || {}).tz || (site?.attrs || {}).timezone || "UTC";
  ctx.siteTz = siteTz;
  if (!q.has("range.lite.chart") && sel.hours > 0) {
    rangeState = { preset: "custom", fromMs: Date.now() - sel.hours * 3600e3, toMs: Date.now() };
    setChartRangeState("lite.chart", rangeState, { push: false });
  }
  const equip = model.equips.find((e) => idOf(e) === sel.equip);
  document.title = `${def.title} · Open-FDD Lite`;
  $("title").textContent = `⚡ ${def.title}`;
  $("sub").textContent = `${site?.name ?? sel.site} · ${equip ? (equip.attrs || {}).dis || equip.name : "all equips"} · ${def.desc}`;
  if (def.pick) {
    const opts = def.pick(ctx);
    if (!opts.some((p) => p.uuid === sel.point)) sel.point = def.defaultPick(ctx);
    $("pick").innerHTML = opts.map((p) => `<option value="${p.uuid}">${esc(p.name)}</option>`).join("");
    $("pick").value = sel.point;
    $("pick").hidden = false;
    $("pick").onchange = () => { sel.point = $("pick").value; draw(); };
  }
  chart = echarts.init($("chart"), null, { renderer: "canvas" });
  window.addEventListener("resize", () => chart.resize());
  await draw();
  window.addEventListener("popstate", () => {
    const restored = new URLSearchParams(location.search), candidate = restored.get("point") || "";
    const opts = def.pick ? def.pick(ctx) : [];
    sel.point = opts.some((p) => p.uuid === candidate) ? candidate : (def.pick ? def.defaultPick(ctx) : "");
    if (def.pick) $("pick").value = sel.point;
    rangeState = getChartRangeState("lite.chart");
    draw();
  });
  setInterval(() => { if (!document.hidden) draw(); }, 5 * 60e3);
}

main().catch((e) => {
  $("err").style.display = "block";
  $("err").textContent = `Could not load the chart: ${e.message}`;
  setLive(false, "error");
});
