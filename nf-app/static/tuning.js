// Sweep tuning editor (Full edition, Tuning tab; #1589): per-role sensor-sweep limits for a site or one equipment.
//
// Values are STORED in SI (fdd.rule_config, rule_id SV-LIMITS) and edited in display units: degF / degC (absolute
// temperature, temperature difference and rate are separate conversions), inH2O / Pa, cfm / gpm / L/s. The tuning hook
// (hooks/tuning.js) validates every change exactly like the SQL renderer before it is stored; the fdd hook applies the
// active revision on its next scheduled run (shipped < site < equipment) and records the revision on each result.
//
// Pure helpers at the top run in node (tests/tuning.test.mjs); the DOM part needs nf.js (api, esc), theme.js (ofddChart),
// role-limits.js (ofddRoleLimits) and plot-spec-data.js (the shipped limits). Classic script: browser global `ofddTuning`.
(function (root) {
  const RL = () => root.ofddRoleLimits || (typeof require !== "undefined" ? require("./role-limits.js") : null);
  const FIELDS = ["lo", "hi", "spike_delta", "flat_tol", "stale_tol", "rate_per_h"];
  const FIELD_LABEL = { lo: "Low", hi: "High", spike_delta: "Spike Δ", flat_tol: "Flatline tol", stale_tol: "Stale tol", rate_per_h: "Rate /h" };

  /** Display unit per quantity for a unit system ("imperial" | "si"); chilled-water flow is gpm in imperial. */
  function unitFor(quantity, system, role) {
    if (system === "si") return RL().SI_UNIT[quantity];
    return { absolute_temperature: "degF", relative_humidity: "%RH", air_pressure: "inH2O", power: "kW",
      volume_flow: /water|chw|hw-|cw-/.test(role || "") ? "gpm" : "cfm" }[quantity];
  }
  const unitLabel = (unit, field) => {
    const d = unit === "degF" ? "°F" : unit === "degC" ? "°C" : unit;
    const kind = RL().FIELD_KIND[field];
    return kind === "absolute" ? d : kind === "rate" ? `Δ${d}/h` : (unit === "degF" || unit === "degC") ? `Δ${d}` : d;
  };
  const round = (v, digits = 4) => (typeof v === "number" && Number.isFinite(v) ? Number(v.toFixed(digits)) : v);

  /** Table rows: [{ role, quantity, unit, fields: {field: {si, shown, source}} }] from a hook "effective" answer. */
  function displayRows(effective, system) {
    return Object.entries(effective.roles).map(([role, e]) => {
      const unit = unitFor(e.quantity, system, role);
      const fields = {};
      for (const f of FIELDS) {
        const si = e[f];
        fields[f] = { si, shown: si == null ? null : round(RL().fromSi(si, unit, e.quantity, f)), source: effective.sources[role][f] };
      }
      return { role, quantity: e.quantity, unit, fields };
    });
  }

  /**
   * The SI override document for a scope from the editor: `edits` = {role: {field: shown value (display unit) | ""}},
   * `current` = the scope's active override (kept for untouched fields), `rows` = displayRows (units, SI values).
   * A field equal (after conversion) to the effective value it would inherit is dropped; "" clears an override.
   */
  function buildOverride(edits, rows, current) {
    const roles = {};
    for (const [role, fields] of Object.entries((current && current.roles) || {})) roles[role] = { ...fields };
    const byRole = new Map(rows.map((r) => [r.role, r]));
    for (const [role, fields] of Object.entries(edits || {})) {
      const row = byRole.get(role);
      if (!row) throw new Error(`unknown role ${role}`);
      for (const [field, text] of Object.entries(fields)) {
        if (!FIELDS.includes(field)) throw new Error(`${field} is not editable`);
        if (text === "" || text == null) { if (roles[role]) delete roles[role][field]; continue; }
        const shown = Number(text);
        if (!Number.isFinite(shown)) throw new Error(`${role} ${FIELD_LABEL[field]}: "${text}" is not a number`);
        const cell = row.fields[field];
        if (cell.shown != null && shown === cell.shown) continue;          // unchanged in display units: keep exact SI
        roles[role] = roles[role] || {};
        roles[role][field] = Number(RL().toSi(shown, row.unit, row.quantity, field).toFixed(6));
      }
      if (roles[role] && !Object.keys(roles[role]).length) delete roles[role];
    }
    return { version: 1, roles };
  }

  /** Low / high bands of one quantity, shipped vs effective, as ECharts options (stacked bars: offset + band). */
  function bandChartOption(rows, shippedDoc, quantity) {
    const sel = rows.filter((r) => r.quantity === quantity);
    const shipped = new Map(shippedDoc.roles.map((e) => [e.role, e]));
    const unit = sel[0] ? sel[0].unit : "";
    const conv = (r, f, v) => round(RL().fromSi(v, r.unit, r.quantity, f), 3);
    const names = sel.map((r) => r.role);
    const base = (vals) => vals.map((v) => v[0]);
    const span = (vals) => vals.map((v) => round(v[1] - v[0], 3));
    const eff = sel.map((r) => [r.fields.lo.shown, r.fields.hi.shown]);
    const shp = sel.map((r) => [conv(r, "lo", shipped.get(r.role).lo), conv(r, "hi", shipped.get(r.role).hi)]);
    const lowest = Math.min(0, ...eff.map((v) => v[0]), ...shp.map((v) => v[0]));
    const off = (vals) => base(vals).map((v) => round(v - lowest, 3));
    return {
      tooltip: { trigger: "axis", formatter: (ps) => {
        const i = ps[0].dataIndex;
        return `${names[i]}<br>shipped ${shp[i][0]} … ${shp[i][1]} ${unitLabel(unit, "lo")}<br>effective ${eff[i][0]} … ${eff[i][1]} ${unitLabel(unit, "lo")}`;
      } },
      legend: { data: ["shipped", "effective"] },
      grid: { left: 170, right: 24, top: 30, bottom: 30 },
      xAxis: { type: "value", name: unitLabel(unit, "lo"), axisLabel: { formatter: (v) => String(round(v + lowest, 2)) } },
      yAxis: { type: "category", data: names },
      series: [
        { name: "_s", type: "bar", stack: "s", itemStyle: { color: "transparent" }, data: off(shp), silent: true },
        { name: "shipped", type: "bar", stack: "s", data: span(shp), barGap: "10%" },
        { name: "_e", type: "bar", stack: "e", itemStyle: { color: "transparent" }, data: off(eff), silent: true },
        { name: "effective", type: "bar", stack: "e", data: span(eff) },
      ],
    };
  }

  // ---- DOM -------------------------------------------------------------------------------------------------------------
  const APP_ID = () => ((typeof location !== "undefined" && location.pathname.match(/\/apps\/static\/([^/]+)\//)) || [])[1] || "open-fdd";
  const st = { scopeKey: "site", answer: null, edits: {}, quantity: "absolute_temperature", busy: false };

  /** Start the tuning hook with string args and wait for its JSON answer (the run's last event). */
  async function callHook(args) {
    const body = Object.fromEntries(Object.entries(args).filter(([, v]) => v != null).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]));
    const { pid } = await api(`/api/v1/apps/${APP_ID()}/hooks/tuning`, body);
    for (let i = 0; i < 30; i++) {
      await new Promise((ok) => setTimeout(ok, 1000));
      const runs = (await api(`/api/v1/apps/${APP_ID()}/hooks/tuning/runs?page_size=5&include_results=true`)).runs || [];
      const run = runs.find((r) => r.pid === pid);
      if (!run || ["STATE_RUNNING", "STATE_ENQUEUED", "STATE_SCHEDULED"].includes(run.state)) continue;
      const events = Object.values(run.results || {}).flatMap((g) => g.events || []);
      const last = [...events].reverse().find((e) => typeof e.message === "string" && e.message.startsWith("{"));
      if (!last) throw new Error(`tuning hook ended ${run.state} without an answer`);
      return JSON.parse(last.message);
    }
    throw new Error("tuning hook still running; try again");
  }

  function render({ scope }) {
    const el = (id) => /** @type {any} */ (document.getElementById(id));
    const status = (t) => (el("tunStatus").textContent = t);
    const equip = scope.equip && (typeof WEATHER_SCOPE === "undefined" || scope.equip !== WEATHER_SCOPE) ? scope.equip : "";
    el("tunScope").innerHTML = `<option value="site">Whole site</option>` + (equip ? `<option value="equip:${esc(equip)}">This equipment: ${esc(equip)}</option>` : "");
    if (st.scopeKey !== "site" && st.scopeKey !== `equip:${equip}`) st.scopeKey = "site";
    el("tunScope").value = st.scopeKey;
    const run = async (args, what) => {
      if (st.busy) return;
      st.busy = true;
      status(`${what}…`);
      try {
        const ans = await callHook({ site: scope.site, scope: st.scopeKey, ...args });
        if (!ans.ok) { status(`${what} refused: ${ans.error}`); return; }
        st.answer = ans;
        if (ans.written) st.edits = {};
        status(ans.written ? `${what}: revision ${ans.revision} stored; the next FDD run uses it` : `${what}: OK${args.action === "preview" ? " (not saved)" : ""}`);
        draw();
      } catch (e) { status(`${what} failed: ${e.message}`); } finally { st.busy = false; }
    };
    const system = () => (typeof unitSystem === "function" ? unitSystem() : "imperial");
    const draw = () => {
      if (!st.answer) return;
      const rows = displayRows(st.answer.effective, system());
      const head = `<tr><th>Role</th>${FIELDS.map((f) => `<th title="used by ${RL().FIELD_RULES[f].join(", ")}">${FIELD_LABEL[f]}</th>`).join("")}</tr>`;
      el("tunRows").innerHTML = head + rows.map((r) => `<tr><td>${esc(r.role)}<div class="hint">${esc(r.quantity.replace(/_/g, " "))}</div></td>${FIELDS.map((f) => {
        const c = r.fields[f];
        if (c.si == null && !(st.edits[r.role] || {})[f]) return `<td class="hint">—</td>`;
        const val = (st.edits[r.role] || {})[f] ?? c.shown;
        return `<td><input class="tun-in src-${c.source}" data-role="${esc(r.role)}" data-field="${f}" value="${esc(val)}" size="7">`
          + `<div class="hint">${esc(unitLabel(r.unit, f))} · ${c.source} · SI ${esc(round(c.si, 6))}</div></td>`;
      }).join("")}</tr>`).join("");
      const hist = st.answer.history || [];
      el("tunHistory").innerHTML = hist.length ? hist.map((h) => `<li>rev ${h.revision}${h.active ? " <b>(active)</b>" : ""} · ${esc(h.created_at)} · ${esc(h.created_by)} · `
        + `${h.parameters && h.parameters.reset ? "reset to defaults" : `${Object.keys((h.parameters && h.parameters.roles) || {}).length} roles`}`
        + `${h.parameters && h.parameters.rollback_of ? ` (rollback of ${h.parameters.rollback_of})` : ""}`
        + `${h.active ? "" : ` <button class="btn" data-rollback="${h.revision}" type="button">Roll back to this</button>`}</li>`).join("") : "<li class=\"hint\">No revisions yet: the shipped limits apply.</li>";
      const shipped = root.ofddPlotSpecData && root.ofddPlotSpecData.sweep_limits;
      const chartEl = el("tunChart");
      if (shipped && chartEl && typeof ofddChart === "function") ofddChart(chartEl).setOption(bandChartOption(rows, shipped, st.quantity), true);
    };
    const pending = () => buildOverride(st.edits, displayRows(st.answer.effective, system()), (st.answer.active[st.scopeKey] || {}).parameters);
    el("tunRows").oninput = (ev) => {
      const t = /** @type {any} */ (ev.target);
      if (!t.dataset || !t.dataset.role) return;
      st.edits[t.dataset.role] = { ...(st.edits[t.dataset.role] || {}), [t.dataset.field]: t.value };
    };
    el("tunScope").onchange = () => { st.scopeKey = el("tunScope").value; st.edits = {}; run({ action: "get" }, "Loading"); };
    el("tunQuantity").onchange = () => { st.quantity = el("tunQuantity").value; draw(); };
    el("tunPreview").onclick = () => { try { run({ action: "preview", overrides: pending() }, "Preview"); } catch (e) { status(e.message); } };
    el("tunSave").onclick = () => { try { run({ action: "save", overrides: pending(), note: el("tunNote").value || undefined }, "Save"); } catch (e) { status(e.message); } };
    el("tunReset").onclick = () => { if (confirm("Reset this scope to the defaults below it? (stored as a new revision)")) run({ action: "reset" }, "Reset"); };
    el("tunHistory").onclick = (ev) => {
      const target = /** @type {any} */ (ev.target);
      const b = target.closest && target.closest("[data-rollback]");
      if (b) run({ action: "rollback", revision: b.dataset.rollback }, `Rollback to ${b.dataset.rollback}`);
    };
    if (!st.answer || st.answer.site !== scope.site || st.answer.scope !== st.scopeKey) return run({ action: "get" }, "Loading");
    draw();
  }

  const exported = { FIELDS, unitFor, unitLabel, displayRows, buildOverride, bandChartOption, render };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  root.ofddTuning = exported;
})(typeof globalThis !== "undefined" ? globalThis : this);
