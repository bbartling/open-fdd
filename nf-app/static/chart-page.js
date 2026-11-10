// chart.html: one catalog chart per window (charts.js), chosen by the query string.
// Needs nf.js, model.js, theme.js and charts.js loaded first.

/** @param {string} id @returns {AnyEl} */
const $ = (id) => /** @type {AnyEl} */ (document.getElementById(id));
const q = new URLSearchParams(location.search);
const sel = { id: q.get("c") || CHARTS[0].id, site: q.get("site") || "", equip: q.get("equip") || "",
  hours: Number(q.get("h")) || 0, point: q.get("point") || "" };
let model, ctx, def;

function setLive(ok, txt) {
  $("liveDot").classList.toggle("bad", !ok);
  $("liveTxt").textContent = txt;
}

function syncUrl() {
  const u = new URLSearchParams({ c: def.id, site: sel.site, h: String(sel.hours) });
  if (sel.equip) u.set("equip", sel.equip);
  if (def.pick && sel.point) u.set("point", sel.point);
  const range = getChartRangeState("charts");
  u.set("range.charts", range.preset);
  if (range.preset === "custom") { u.set("from.charts", String(range.fromMs)); u.set("to.charts", String(range.toMs)); }
  history.replaceState(null, "", `?${u}`);
}

async function draw() {
  const state = getChartRangeState("charts"), site = model.sites.find((s) => idOf(s) === sel.site);
  const siteTz = chartTimeZone(site?.attrs?.tz || site?.attrs?.timezone);
  renderRangeControl($("range"), { key: "charts", state, siteTz, onChange: () => draw() });
  const baseCtx = pointSets(model, sel.site, sel.equip);
  const candidate = def.pick ? def.pick(baseCtx) : [...baseCtx.cards, ...baseCtx.status, ...baseCtx.weather];
  setLive(true, "loading history range…");
  syncUrl();
  try {
    const range = await resolveChartSelection(candidate, state, { siteTz });
    const ctx = { ...baseCtx, range, siteTz };
    const hours = Math.max(1, (range.resolvedBounds.toMs - range.resolvedBounds.fromMs) / 3600e3);
    const hint = await drawChart(ofddChart($("chart")), def, ctx, hours, { point: sel.point, range, siteTz });
    if (hint != null) $("hint").textContent = hint;
    setLive(true, `updated ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    $("hint").textContent = `Could not load this range: ${e.message}`;
    setLive(false, e.message);
  }
}

async function main() {
  // chart.html may not list units.js; the display-unit helpers in charts.js need it.
  if (typeof ofddUnits === "undefined") await loadScript("units.js").catch(() => {});
  window.addEventListener("storage", (e) => { if (e.key === "openfdd-units") draw(); });  // toggled in the dashboard
  await initAuth();
  model = await loadModel();
  if (!model.sites.some((s) => idOf(s) === sel.site)) sel.site = idOf(model.sites[0]);
  ctx = pointSets(model, sel.site, sel.equip);
  def = chartDef(sel.id);
  if (!def || !def.applies(ctx)) throw new Error(`chart "${sel.id}" has no matching tagged points here`);
  if (!sel.hours) sel.hours = def.range;
  const site = model.sites.find((s) => idOf(s) === sel.site);
  const equip = model.equips.find((e) => idOf(e) === sel.equip);
  document.title = `${def.title} · Open-FDD`;
  $("title").textContent = `⚡ ${def.title}`;
  $("sub").textContent = `${site?.name ?? sel.site} · ${equip ? (equip.attrs || {}).dis || equip.name : "all equips"} · ${def.desc}`;
  if (def.pick) {
    const opts = def.pick(ctx);
    if (!opts.some((p) => p.uuid === sel.point)) sel.point = def.defaultPick(ctx);
    $("pick").innerHTML = opts.map((p) => `<option value="${p.uuid}">${esc(p.name)}</option>`).join("");
    $("pick").value = sel.point;
    $("pick").classList.remove("hidden");
    $("pick").onchange = () => { sel.point = $("pick").value; draw(); };
  }
  window.addEventListener("popstate", () => draw());
  onThemeChange(draw);
  await draw();
  setInterval(() => { if (!document.hidden) draw(); }, 5 * 60e3);
}

main().catch((e) => {
  $("err").style.display = "block";
  $("err").textContent = `Could not load the chart: ${e.message}`;
  setLive(false, "error");
});
