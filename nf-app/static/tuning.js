// Inline FDD Tuners & sweep tuning client (Full edition, #1589 & 5.0.17).
//
// Values are STORED in SI (`fdd.rule_config`: rule_id `<RULE_ID>` and `SV-LIMITS`) and edited in display units:
// degF / degC (absolute temperature, temperature difference and rate are separate conversions), inH2O / Pa / psi,
// cfm / gpm / L/s, kWh / kBtu, %RH, %, min / sec. The tuning hook (hooks/tuning.js) validates every change identically
// to the SQL renderer before storing a revision; the fdd hook applies active revisions on its next run (shipped < site < equip).
//
// Pure helpers at the top run in node (tests/role-limits.test.mjs, tests/rule-tuning.test.mjs).
// Classic script: browser global `ofddTuning`.
(function (root) {
  const RL = () => root.ofddRoleLimits || (typeof require !== "undefined" ? require("./role-limits.js") : null);
  const RT = () => root.ofddRuleTuning || (typeof require !== "undefined" ? require("./rule-tuning.js") : null);
  const FIELDS = ["lo", "hi", "spike_delta", "flat_tol", "stale_tol", "rate_per_h"];
  const FIELD_LABEL = { lo: "Low", hi: "High", spike_delta: "Spike Δ", flat_tol: "Flatline tol", stale_tol: "Stale tol", rate_per_h: "Rate /h" };

  /** Display unit per quantity for a unit system ("imperial" | "si"); chilled-water flow is gpm in imperial. */
  function unitFor(quantity, system, role) {
    if (system === "si") return RL().SI_UNIT[quantity];
    return {
      absolute_temperature: "degF", relative_humidity: "%RH", air_pressure: "inH2O", power: "kW",
      volume_flow: /water|chw|hw-|cw-/.test(role || "") ? "gpm" : "cfm",
    }[quantity];
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
   * The SI override document for a scope from the editor: `edits` = {role: {field: shown value (display unit) | "" | {text, unit}}},
   * `current` = the scope's active override (kept for untouched fields), `rows` = displayRows (units, SI values).
   */
  function buildOverride(edits, rows, current, allowedFields, allowedRoles) {
    const roles = {};
    for (const [role, fields] of Object.entries((current && current.roles) || {})) roles[role] = { ...fields };
    const byRole = new Map(rows.map((r) => [r.role, r]));
    const fieldSet = allowedFields ? new Set(allowedFields) : null;
    const roleSet = allowedRoles ? new Set(allowedRoles) : null;
    for (const [role, fields] of Object.entries(edits || {})) {
      if (roleSet && !roleSet.has(role)) continue;
      const row = byRole.get(role);
      if (!row) throw new Error(`unknown role ${role}`);
      for (const [field, rawEdit] of Object.entries(fields)) {
        if (fieldSet && !fieldSet.has(field)) continue;
        if (!FIELDS.includes(field)) throw new Error(`${field} is not editable`);
        const isObj = rawEdit && typeof rawEdit === "object" && !Array.isArray(rawEdit);
        const text = isObj ? rawEdit.text : rawEdit;
        const editUnit = isObj && rawEdit.unit ? rawEdit.unit : row.unit;
        if (text === "" || text == null) { if (roles[role]) delete roles[role][field]; continue; }
        const shown = Number(text);
        if (!Number.isFinite(shown)) throw new Error(`${role} ${FIELD_LABEL[field]}: "${text}" is not a number`);
        const cell = row.fields[field];
        if (editUnit === row.unit && cell.shown != null && shown === cell.shown) continue;
        roles[role] = roles[role] || {};
        roles[role][field] = Number(RL().toSi(shown, editUnit, row.quantity, field).toFixed(6));
      }
      if (roles[role] && !Object.keys(roles[role]).length) delete roles[role];
    }
    return { version: 1, roles };
  }

  /** Low / high bands of one quantity, shipped vs effective, as ECharts options. */
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

  // ---- Per-rule tuners pure helpers (5.0.17) ---------------------------------------------------------------------------
  function sweepFieldsForRule(ruleId) {
    return FIELDS.filter((f) => (RL().FIELD_RULES[f] || []).includes(ruleId));
  }

  /** Map a rule's bound inputs (`bound = { roleKey: [points] }`) to unique SV-LIMITS role names in model order. */
  function assessableSweepRoles(bound, catalog) {
    if (!bound || !catalog || !catalog.roles) return [];
    const out = [];
    const seen = new Set();
    for (const [roleKey, pts] of Object.entries(bound)) {
      if (!Array.isArray(pts) || !pts.length) continue;
      const roleName = catalog.roles[roleKey] && catalog.roles[roleKey].name;
      if (roleName && !seen.has(roleName)) { seen.add(roleName); out.push(roleName); }
    }
    return out;
  }

  /**
   * Build `{ version: 1, params: { ... } }` in SI from UI draft edits (`{ key: raw | { text, unit } | boolean }`).
   * Preserves untouched active params in `current`; `""` clears an override; throws on invalid/out-of-bounds values.
   */
  function buildRuleOverride(edits, controls, effectiveParams, current, system, ruleId) {
    const rt = RT();
    const params = { ...((current && current.params) || {}) };
    for (const [key, rawEdit] of Object.entries(edits || {})) {
      const ctrl = controls && controls[key];
      if (!ctrl) throw new Error(`${key} is not a tunable SQL parameter`);
      const effSi = effectiveParams && Object.prototype.hasOwnProperty.call(effectiveParams, key) ? effectiveParams[key] : ctrl.default;
      const dispUnit = rt.preferredDisplayUnit(ctrl, system, ruleId);
      if (ctrl.kind === "boolean") {
        const val = (rawEdit && typeof rawEdit === "object" && "checked" in rawEdit) ? (rawEdit.checked ? 1 : 0) : (rawEdit === true || rawEdit === 1 || rawEdit === "1" || rawEdit === "true" ? 1 : 0);
        if (rawEdit === "" || rawEdit == null) { delete params[key]; continue; }
        if (val === (Number(effSi) ? 1 : 0) && !Object.prototype.hasOwnProperty.call(params, key)) continue;
        params[key] = val;
        continue;
      }
      const isObj = rawEdit && typeof rawEdit === "object" && !Array.isArray(rawEdit);
      const text = isObj ? rawEdit.text : rawEdit;
      const editUnit = isObj && rawEdit.unit ? rawEdit.unit : dispUnit;
      if (text === "" || text == null) { delete params[key]; continue; }
      const shown = Number(text);
      if (!Number.isFinite(shown)) throw new Error(`${ctrl.label || key}: "${text}" is not a finite number`);
      const effShown = round(rt.fromSi(effSi, dispUnit, ctrl.kind), 4);
      if (editUnit === dispUnit && effShown != null && shown === effShown && !Object.prototype.hasOwnProperty.call(params, key)) continue;
      const si = Number(rt.toSi(shown, editUnit, ctrl.kind).toFixed(6));
      if (si < ctrl.min || si > ctrl.max) {
        const minDisp = round(rt.fromSi(ctrl.min, editUnit, ctrl.kind), 4);
        const maxDisp = round(rt.fromSi(ctrl.max, editUnit, ctrl.kind), 4);
        throw new Error(`${ctrl.label || key}: ${shown} ${editUnit} is outside [${minDisp}, ${maxDisp}] ${editUnit}`);
      }
      params[key] = si;
    }
    return rt.normalizeRuleOverride({ version: 1, params }, controls, ruleId);
  }

  /** Clear only `allowedFields` (for `allowedRoles`, or all roles if null) from an SV-LIMITS doc, preserving siblings. */
  function resetSweepOverrideForRule(current, allowedFields, allowedRoles) {
    const roles = {};
    const fieldSet = new Set(allowedFields || []);
    const roleSet = allowedRoles && allowedRoles.length ? new Set(allowedRoles) : null;
    for (const [role, fields] of Object.entries((current && current.roles) || {})) {
      const next = {};
      for (const [f, v] of Object.entries(fields || {})) {
        if (fieldSet.has(f) && (!roleSet || roleSet.has(role))) continue;
        next[f] = v;
      }
      if (Object.keys(next).length) roles[role] = next;
    }
    return { version: 1, roles };
  }

  /** Roll back only `allowedFields` (within `allowedRoles` if provided) from `targetDoc` into `current`. */
  function rollbackSweepOverrideForRule(targetDoc, current, allowedFields, allowedRoles) {
    const next = resetSweepOverrideForRule(current, allowedFields, allowedRoles);
    const fieldSet = new Set(allowedFields || []);
    const roleSet = allowedRoles && allowedRoles.length ? new Set(allowedRoles) : null;
    for (const [role, fields] of Object.entries((targetDoc && targetDoc.roles) || {})) {
      if (roleSet && !roleSet.has(role)) continue;
      for (const [f, v] of Object.entries(fields || {})) {
        if (!fieldSet.has(f)) continue;
        next.roles[role] = next.roles[role] || {};
        next.roles[role][f] = v;
      }
    }
    return next;
  }

  function unitNice(unit) {
    if (unit === "degF") return "°F";
    if (unit === "degC") return "°C";
    if (unit === "degF/h") return "°F/h";
    if (unit === "degC/h") return "°C/h";
    return unit || "";
  }

  function shippedControlEffective(ruleId) {
    const rt = RT();
    const spec = root.ofddPlotSpecData && root.ofddPlotSpecData.rule_tuning && root.ofddPlotSpecData.rule_tuning.rules;
    const ruleTpl = spec && spec[ruleId];
    if (!ruleTpl || !ruleTpl.controls) return null;
    const merged = rt.mergeRuleParams(ruleTpl.controls, null, null, ruleId);
    return { controls: ruleTpl.controls, effective: { params: merged.effective, sources: merged.sources }, active: {}, history: [] };
  }

  // ---- DOM (inline FDD Tuners inside #fddPlotPanel) -------------------------------------------------------------------
  const APP_ID = () => ((typeof location !== "undefined" && location.pathname.match(/\/apps\/static\/([^/]+)\//)) || [])[1] || "open-fdd";
  const st = {
    gen: 0,
    context: null,       // { site, equip, equipLabel, ruleId, bound, catalog }
    scopeKey: "site",
    ruleResp: null,      // hook answer for ruleId (if rule has controls)
    limitsResp: null,    // hook answer for SV-LIMITS (if rule is a sweep)
    readOnlyReason: "",
    busy: false,
    drafts: new Map(),   // `${site}|${equip}|${ruleId}|${scopeKey}` -> { params: {}, sweeps: {}, note: "" }
    status: "",
    statusIsErr: false,
  };

  function draftKey(ctx, scopeKey) {
    return `${ctx.site || ""}|${ctx.equip || ""}|${ctx.ruleId || ""}|${scopeKey || "site"}`;
  }
  function getDraft(ctx, scopeKey) {
    const k = draftKey(ctx, scopeKey);
    if (!st.drafts.has(k)) st.drafts.set(k, { params: {}, sweeps: {}, note: "" });
    return st.drafts.get(k);
  }
  function clearDraft(ctx, scopeKey) {
    st.drafts.delete(draftKey(ctx, scopeKey));
  }

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

  function hasControls(ruleId) {
    const spec = root.ofddPlotSpecData && root.ofddPlotSpecData.rule_tuning && root.ofddPlotSpecData.rule_tuning.rules;
    const r = spec && spec[ruleId];
    return !!(r && r.controls && Object.keys(r.controls).length);
  }

  function isSweepRule(ruleId) {
    return RL().SWEEP_RULES.includes(ruleId);
  }

  async function loadInlineState(ctx, scopeKey, gen) {
    st.readOnlyReason = "";
    st.status = "Loading tuners…";
    st.statusIsErr = false;
    drawInline();
    const wantParams = hasControls(ctx.ruleId);
    const wantSweep = isSweepRule(ctx.ruleId);
    if (!wantParams && !wantSweep) {
      st.ruleResp = null;
      st.limitsResp = null;
      st.status = "";
      drawInline();
      return;
    }
    let ruleAns = null;
    let limitsAns = null;
    let readOnly = "";
    try {
      if (wantParams) {
        ruleAns = await callHook({ action: "get", site: ctx.site, scope: scopeKey, rule_id: ctx.ruleId });
        if (gen !== st.gen) return;
        if (ruleAns && ruleAns.ok && ruleAns.role_limits) {
          limitsAns = { ok: true, site: ctx.site, scope: scopeKey, rule_id: RL().LIMITS_RULE_ID, ...ruleAns.role_limits };
        }
      }
      if (wantSweep && (!limitsAns || !limitsAns.ok)) {
        limitsAns = await callHook({ action: "get", site: ctx.site, scope: scopeKey, rule_id: RL().LIMITS_RULE_ID });
        if (gen !== st.gen) return;
      }
      if ((ruleAns && !ruleAns.ok) || (limitsAns && !limitsAns.ok)) {
        readOnly = (ruleAns && !ruleAns.ok && ruleAns.error) || (limitsAns && !limitsAns.ok && limitsAns.error) || "Tuning storage unavailable";
      }
    } catch (e) {
      if (gen !== st.gen) return;
      readOnly = /401|403|unauthorized|forbidden/i.test(e.message)
        ? "Read-only: console write permission is required to preview or save tuning revisions."
        : `Read-only (${e.message})`;
    }
    if (gen !== st.gen) return;

    // Fallback to shipped defaults when Timescale / hook access is read-only so users still see shipped bounds.
    if (wantParams && (!ruleAns || !ruleAns.ok)) {
      ruleAns = shippedControlEffective(ctx.ruleId);
    }
    if (wantSweep && (!limitsAns || !limitsAns.ok)) {
      const shipped = root.ofddPlotSpecData && root.ofddPlotSpecData.sweep_limits;
      if (shipped) {
        const m = RL().merge(shipped);
        limitsAns = {
          ok: false,
          active: {},
          effective: { roles: Object.fromEntries(m.doc.roles.map((e) => [e.role, e])), sources: m.sources },
          history: [],
        };
      }
    }
    st.ruleResp = ruleAns;
    st.limitsResp = limitsAns;
    st.readOnlyReason = readOnly;
    st.status = "";
    drawInline();
  }

  function drawInline() {
    const host = typeof document !== "undefined" ? document.getElementById("fddTunersPanel") : null;
    if (!host) return;
    const ctx = st.context;
    if (!ctx) { host.innerHTML = ""; return; }
    const escFn = typeof esc === "function" ? esc : (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
    const sys = typeof unitSystem === "function" ? unitSystem() : "imperial";
    const rt = RT();
    const wantParams = hasControls(ctx.ruleId);
    const wantSweep = isSweepRule(ctx.ruleId);
    const scopeOptions = (ctx.equip ? `<option value="equip:${escFn(ctx.equip)}">This equipment (${escFn(ctx.equipLabel || ctx.equip)})</option>` : "")
      + `<option value="site">Whole site (affects all matching equipment on site)</option>`;

    if (!wantParams && !wantSweep) {
      host.innerHTML = `<div class="tuners-head"><h3>Tuners · ${escFn(ctx.ruleId)}</h3></div>`
        + `<p class="hint">This rule has no tunable SQL parameters.</p>`;
      return;
    }

    const draft = getDraft(ctx, st.scopeKey);
    const readOnly = !!st.readOnlyReason;
    const sweepFields = wantSweep ? sweepFieldsForRule(ctx.ruleId) : [];
    const boundRoles = wantSweep ? assessableSweepRoles(ctx.bound, ctx.catalog) : [];
    const effLimits = st.limitsResp && st.limitsResp.effective;
    const allSweepRows = effLimits ? displayRows(effLimits, sys) : [];
    const sweepRows = boundRoles.length
      ? allSweepRows.filter((r) => boundRoles.includes(r.role))
      : allSweepRows;

    const paramResp = st.ruleResp;
    const controls = (paramResp && paramResp.controls) || {};
    const effParams = (paramResp && paramResp.effective && paramResp.effective.params) || {};
    const paramSources = (paramResp && paramResp.effective && paramResp.effective.sources) || {};

    let controlsHtml = "";
    if (wantParams && Object.keys(controls).length) {
      controlsHtml += `<div class="tuners-grid">`;
      for (const [key, ctrl] of Object.entries(controls)) {
        const src = paramSources[key] || "shipped";
        const srcCls = src === "site" ? "src-site" : src === "equip" ? "src-equipment" : "";
        const effSi = effParams[key] ?? ctrl.default;
        if (ctrl.kind === "boolean") {
          const checked = Object.prototype.hasOwnProperty.call(draft.params, key)
            ? !!draft.params[key].checked
            : !!Number(effSi);
          controlsHtml += `<div class="tun-card ${srcCls}">`
            + `<label><span>${escFn(ctrl.label || key)}</span><span class="hint">${escFn(src)}</span></label>`
            + `<label class="tun-card-check"><input type="checkbox" data-param-bool="${escFn(key)}"${checked ? " checked" : ""}${readOnly ? " disabled" : ""}> `
            + `<span>${checked ? "Enabled (1)" : "Disabled (0)"}</span></label>`
            + `<div class="hint">default ${ctrl.default ? "enabled" : "disabled"}</div></div>`;
        } else {
          const unit = rt.preferredDisplayUnit(ctrl, sys, ctx.ruleId);
          const uLabel = unitNice(unit);
          const shown = round(rt.fromSi(effSi, unit, ctrl.kind), 4);
          const minDisp = round(rt.fromSi(ctrl.min, unit, ctrl.kind), 4);
          const maxDisp = round(rt.fromSi(ctrl.max, unit, ctrl.kind), 4);
          const defDisp = round(rt.fromSi(ctrl.default, unit, ctrl.kind), 4);
          const dEntry = draft.params[key];
          const val = dEntry ? (dEntry.unit === unit ? dEntry.text : round(rt.fromSi(rt.toSi(Number(dEntry.text), dEntry.unit, ctrl.kind), unit, ctrl.kind), 4)) : shown;
          controlsHtml += `<div class="tun-card ${srcCls}">`
            + `<label for="tun-p-${escFn(key)}"><span>${escFn(ctrl.label || key)}</span><span class="hint">${escFn(uLabel)} · ${escFn(src)}</span></label>`
            + `<input id="tun-p-${escFn(key)}" type="number" step="any" data-param="${escFn(key)}" data-unit="${escFn(unit)}" value="${escFn(val)}"${readOnly ? " disabled" : ""}>`
            + `<div class="hint">default ${escFn(defDisp)} ${escFn(uLabel)} · range ${escFn(minDisp)}–${escFn(maxDisp)} · SI ${escFn(round(effSi, 6))}</div></div>`;
        }
      }
      controlsHtml += `</div>`;
    }

    let sweepHtml = "";
    if (wantSweep) {
      if (!sweepRows.length) {
        sweepHtml = `<p class="hint">No assessable sensor-sweep roles bound on this equipment for ${escFn(ctx.ruleId)}.</p>`;
      } else {
        const head = `<tr><th>Sensor role</th>${sweepFields.map((f) => `<th>${escFn(FIELD_LABEL[f])}</th>`).join("")}</tr>`;
        const body = sweepRows.map((r) => {
          const cells = sweepFields.map((f) => {
            const c = r.fields[f];
            if (c.si == null && !(draft.sweeps[r.role] || {})[f]) return `<td class="hint">—</td>`;
            const dEntry = (draft.sweeps[r.role] || {})[f];
            const val = dEntry
              ? (dEntry.unit === r.unit ? dEntry.text : round(RL().fromSi(RL().toSi(Number(dEntry.text), dEntry.unit, r.quantity, f), r.unit, r.quantity, f), 4))
              : c.shown;
            return `<td><input class="tun-in src-${escFn(c.source)}" type="number" step="any" data-role="${escFn(r.role)}" data-field="${escFn(f)}" data-unit="${escFn(r.unit)}" value="${escFn(val)}" size="7"${readOnly ? " disabled" : ""}>`
              + `<div class="hint">${escFn(unitLabel(r.unit, f))} · ${escFn(c.source)} · SI ${escFn(round(c.si, 6))}</div></td>`;
          }).join("");
          return `<tr><td>${escFn(r.role)}<div class="hint">${escFn(r.quantity.replace(/_/g, " "))}</div></td>${cells}</tr>`;
        }).join("");
        sweepHtml = `<h4 class="tuners-subhead">Per-role sensor limits (${escFn(ctx.ruleId)} fields only · saved to SV-LIMITS)</h4>`
          + `<div class="tablewrap"><table class="tun-table" id="tunSweepRows">${head}${body}</table></div>`;
      }
    }

    const ruleHist = (paramResp && paramResp.history) || [];
    const limitsHist = (st.limitsResp && st.limitsResp.history) || [];
    const renderHistList = (items, kind) => items.length ? items.map((h) => `<li>rev ${h.revision}${h.active ? " <b>(active)</b>" : ""} · ${escFn(h.created_at)} · ${escFn(h.created_by)}`
      + `${h.parameters && h.parameters.note ? ` · "${escFn(h.parameters.note)}"` : ""}`
      + `${h.parameters && h.parameters.reset ? " · reset" : ""}`
      + `${h.parameters && h.parameters.rollback_of ? ` · rollback of ${escFn(h.parameters.rollback_of)}` : ""}`
      + `${!readOnly && !h.active ? ` <button class="btn" data-rollback="${h.revision}" data-rb-kind="${kind}" type="button">Roll back ${kind === "limits" ? `${escFn(ctx.ruleId)} fields` : "to this"}</button>` : ""}</li>`).join("")
      : `<li class="hint">No saved revisions yet; shipped defaults apply.</li>`;

    const scopeWarn = st.scopeKey === "site" && ctx.equip
      ? `<span class="hint">Whole-site scope applies to every matching equipment on site ${escFn(ctx.site || "default")}.</span>`
      : "";

    host.innerHTML = `<div class="tuners-head">`
      + `<h3>Tuners · ${escFn(ctx.ruleId)}${ctx.equipLabel ? ` · ${escFn(ctx.equipLabel)}` : ""} <span class="hint">site ${escFn(ctx.site || "default")} · stored in SI</span></h3>`
      + `<div class="tuners-scope"><label>Scope <select id="tunScope">${scopeOptions}</select></label>${scopeWarn}</div>`
      + `</div>`
      + (readOnly ? `<div class="tun-banner">${escFn(st.readOnlyReason)} Showing shipped defaults read-only.</div>` : "")
      + (st.status ? `<div class="tun-banner${st.statusIsErr ? " err" : ""}" id="tunStatus" role="status">${escFn(st.status)}</div>` : `<div class="hint" id="tunStatus" role="status"></div>`)
      + controlsHtml
      + sweepHtml
      + `<div class="exbar">`
      + `<label class="hint">Note <input id="tunNote" maxlength="200" placeholder="why (stored with revision)" value="${escFn(draft.note || "")}"${readOnly ? " disabled" : ""}></label>`
      + `<button class="btn" id="tunPreview" type="button"${readOnly ? " disabled" : ""}>Preview</button>`
      + `<button class="btn primary" id="tunSave" type="button"${readOnly ? " disabled" : ""}>Save revision</button>`
      + `<button class="btn" id="tunReset" type="button"${readOnly ? " disabled" : ""}>Reset ${escFn(ctx.ruleId)} to inherited</button>`
      + `<button class="btn" id="tunReload" type="button">Reload latest</button>`
      + `</div>`
      + `<details class="tun-history"><summary>Revision history (${ruleHist.length + limitsHist.length})</summary>`
      + (wantParams ? `<div class="hint">${escFn(ctx.ruleId)} parameter revisions:</div><ul>${renderHistList(ruleHist, "rule")}</ul>` : "")
      + (wantSweep ? `<div class="hint">SV-LIMITS revisions (rolling back here restores only ${escFn(ctx.ruleId)} fields):</div><ul>${renderHistList(limitsHist, "limits")}</ul>` : "")
      + `</details>`;

    const scopeEl = /** @type {HTMLSelectElement | null} */ (document.getElementById("tunScope"));
    if (scopeEl) scopeEl.value = st.scopeKey;

    wireInlineEvents(host, ctx, { wantParams, wantSweep, controls, effParams, sweepRows, sweepFields, boundRoles });
  }

  function wireInlineEvents(host, ctx, meta) {
    const draft = getDraft(ctx, st.scopeKey);
    const setStatus = (msg, isErr = false) => {
      st.status = msg;
      st.statusIsErr = isErr;
      const el = document.getElementById("tunStatus");
      if (el) {
        el.textContent = msg;
        el.className = msg ? `tun-banner${isErr ? " err" : ""}` : "hint";
      }
    };
    const scopeEl = /** @type {HTMLSelectElement | null} */ (document.getElementById("tunScope"));
    if (scopeEl) {
      scopeEl.onchange = () => {
        st.scopeKey = scopeEl.value;
        loadInlineState(ctx, st.scopeKey, ++st.gen);
      };
    }
    const noteEl = /** @type {HTMLInputElement | null} */ (document.getElementById("tunNote"));
    if (noteEl) noteEl.oninput = () => { draft.note = noteEl.value; };

    host.oninput = (ev) => {
      const t = /** @type {any} */ (ev.target);
      if (!t || !t.dataset) return;
      if (t.dataset.param) {
        draft.params[t.dataset.param] = { text: t.value, unit: t.dataset.unit };
      } else if (t.dataset.role && t.dataset.field) {
        draft.sweeps[t.dataset.role] = { ...(draft.sweeps[t.dataset.role] || {}), [t.dataset.field]: { text: t.value, unit: t.dataset.unit } };
      }
    };
    host.onchange = (ev) => {
      const t = /** @type {any} */ (ev.target);
      if (t && t.dataset && t.dataset.paramBool) {
        draft.params[t.dataset.paramBool] = { checked: !!t.checked };
      }
    };

    const sys = typeof unitSystem === "function" ? unitSystem() : "imperial";
    const activeRuleRev = () => {
      const a = st.ruleResp && st.ruleResp.active && st.ruleResp.active[st.scopeKey];
      return a ? a.revision : 0;
    };
    const activeLimitsRev = () => {
      const a = st.limitsResp && st.limitsResp.active && st.limitsResp.active[st.scopeKey];
      return a ? a.revision : 0;
    };

    const runAction = async (mode) => {
      if (st.busy) return;
      st.busy = true;
      const gen = st.gen;
      try {
        setStatus(mode === "preview" ? "Validating…" : "Saving…");
        const note = (draft.note || "").trim() || undefined;
        let wroteRev = null;
        if (meta.wantParams && (mode === "preview" || mode === "save")) {
          const curRule = st.ruleResp && st.ruleResp.active && st.ruleResp.active[st.scopeKey] && st.ruleResp.active[st.scopeKey].parameters;
          const ov = buildRuleOverride(draft.params, meta.controls, meta.effParams, curRule, sys, ctx.ruleId);
          const ans = await callHook({
            action: mode, site: ctx.site, scope: st.scopeKey, rule_id: ctx.ruleId,
            overrides: ov, expected_revision: mode === "save" ? activeRuleRev() : undefined, note,
          });
          if (gen !== st.gen) return;
          if (!ans.ok) {
            if (ans.code === "revision_conflict") {
              setStatus(`Revision conflict on ${ctx.ruleId} (active is now rev ${ans.active_revision}). Click "Reload latest" before saving again.`, true);
            } else {
              setStatus(`${mode} refused: ${ans.error}`, true);
            }
            return;
          }
          if (mode === "save") { st.ruleResp = ans; wroteRev = ans.revision; }
        }
        if (meta.wantSweep && (mode === "preview" || mode === "save")) {
          const curLim = st.limitsResp && st.limitsResp.active && st.limitsResp.active[st.scopeKey] && st.limitsResp.active[st.scopeKey].parameters;
          const ovLim = buildOverride(draft.sweeps, meta.sweepRows, curLim, meta.sweepFields, meta.boundRoles);
          const ans = await callHook({
            action: mode, site: ctx.site, scope: st.scopeKey, rule_id: RL().LIMITS_RULE_ID,
            overrides: ovLim, expected_revision: mode === "save" ? activeLimitsRev() : undefined, note,
          });
          if (gen !== st.gen) return;
          if (!ans.ok) {
            if (ans.code === "revision_conflict") {
              setStatus(`Revision conflict on SV-LIMITS (active is now rev ${ans.active_revision}). Click "Reload latest" before saving again.`, true);
            } else {
              setStatus(`${mode} refused: ${ans.error}`, true);
            }
            return;
          }
          if (mode === "save") { st.limitsResp = ans; wroteRev = wroteRev != null ? `${wroteRev} / SV-LIMITS ${ans.revision}` : ans.revision; }
        }
        if (mode === "preview") {
          setStatus("Validated (read-only preview — bounds and SQL rendering passed; nothing saved or re-run).");
          return;
        }
        clearDraft(ctx, st.scopeKey);
        st.status = `Saved revision ${wroteRev}; the next FDD run applies it.`;
        st.statusIsErr = false;
        await loadInlineState(ctx, st.scopeKey, gen);
      } catch (e) {
        if (gen === st.gen) setStatus(e.message, true);
      } finally {
        st.busy = false;
      }
    };

    const previewBtn = document.getElementById("tunPreview");
    if (previewBtn) previewBtn.onclick = () => runAction("preview");
    const saveBtn = document.getElementById("tunSave");
    if (saveBtn) saveBtn.onclick = () => runAction("save");

    const resetBtn = document.getElementById("tunReset");
    if (resetBtn) {
      resetBtn.onclick = async () => {
        if (st.busy) return;
        if (!confirm(`Reset ${ctx.ruleId} overrides in ${st.scopeKey} to inherited defaults? (stored as a new revision)`)) return;
        st.busy = true;
        const gen = st.gen;
        try {
          setStatus("Resetting…");
          if (meta.wantParams) {
            const ans = await callHook({ action: "reset", site: ctx.site, scope: st.scopeKey, rule_id: ctx.ruleId, expected_revision: activeRuleRev() });
            if (gen !== st.gen) return;
            if (!ans.ok) { setStatus(`Reset refused: ${ans.error}`, true); return; }
          }
          if (meta.wantSweep) {
            const curLim = st.limitsResp && st.limitsResp.active && st.limitsResp.active[st.scopeKey] && st.limitsResp.active[st.scopeKey].parameters;
            const pruned = resetSweepOverrideForRule(curLim, meta.sweepFields, meta.boundRoles);
            const ans = await callHook({
              action: "save", site: ctx.site, scope: st.scopeKey, rule_id: RL().LIMITS_RULE_ID,
              overrides: pruned, expected_revision: activeLimitsRev(), note: `reset ${ctx.ruleId}`,
            });
            if (gen !== st.gen) return;
            if (!ans.ok) { setStatus(`Reset refused: ${ans.error}`, true); return; }
          }
          clearDraft(ctx, st.scopeKey);
          await loadInlineState(ctx, st.scopeKey, gen);
          setStatus(`Reset ${ctx.ruleId} to inherited defaults; the next FDD run applies it.`);
        } catch (e) {
          if (gen === st.gen) setStatus(`Reset failed: ${e.message}`, true);
        } finally {
          st.busy = false;
        }
      };
    }

    const reloadBtn = document.getElementById("tunReload");
    if (reloadBtn) reloadBtn.onclick = () => loadInlineState(ctx, st.scopeKey, ++st.gen);

    const histDetails = host.querySelector(".tun-history");
    if (histDetails) {
      histDetails.onclick = async (ev) => {
        const b = /** @type {any} */ (ev.target).closest && /** @type {any} */ (ev.target).closest("[data-rollback]");
        if (!b || st.busy) return;
        st.busy = true;
        const gen = st.gen;
        try {
          const rev = Number(b.dataset.rollback);
          const kind = b.dataset.rbKind;
          setStatus(`Rolling back to revision ${rev}…`);
          if (kind === "rule") {
            const ans = await callHook({ action: "rollback", site: ctx.site, scope: st.scopeKey, rule_id: ctx.ruleId, revision: rev, expected_revision: activeRuleRev() });
            if (gen !== st.gen) return;
            if (!ans.ok) { setStatus(`Rollback refused: ${ans.error}`, true); return; }
          } else {
            const targetEntry = ((st.limitsResp && st.limitsResp.history) || []).find((h) => Number(h.revision) === rev);
            const curLim = st.limitsResp && st.limitsResp.active && st.limitsResp.active[st.scopeKey] && st.limitsResp.active[st.scopeKey].parameters;
            if (targetEntry && targetEntry.parameters) {
              const merged = rollbackSweepOverrideForRule(targetEntry.parameters, curLim, meta.sweepFields, meta.boundRoles);
              const ans = await callHook({
                action: "save", site: ctx.site, scope: st.scopeKey, rule_id: RL().LIMITS_RULE_ID,
                overrides: merged, expected_revision: activeLimitsRev(), note: `rollback ${ctx.ruleId} to rev ${rev}`,
              });
              if (gen !== st.gen) return;
              if (!ans.ok) { setStatus(`Rollback refused: ${ans.error}`, true); return; }
            }
          }
          clearDraft(ctx, st.scopeKey);
          await loadInlineState(ctx, st.scopeKey, gen);
          setStatus(`Rolled back ${ctx.ruleId} to revision ${rev}; the next FDD run applies it.`);
        } catch (e) {
          if (gen === st.gen) setStatus(`Rollback failed: ${e.message}`, true);
        } finally {
          st.busy = false;
        }
      };
    }
  }

  /**
   * Render inline Tuners for a clicked FDD rule (`showRulePlot` in app.js).
   * Initializes scope to `equip:<equip>` when an equipment is selected, preserves unsaved drafts per
   * `${site}|${equip}|${ruleId}|${scopeKey}`, and increments `st.gen` so stale loads never overwrite.
   */
  function renderInline(ctx) {
    const prev = st.context;
    const sameCtx = prev && prev.site === ctx.site && prev.equip === ctx.equip && prev.ruleId === ctx.ruleId;
    st.context = ctx;
    if (!sameCtx) {
      st.scopeKey = ctx.equip ? `equip:${ctx.equip}` : "site";
      st.ruleResp = null;
      st.limitsResp = null;
      st.status = "";
      st.statusIsErr = false;
      loadInlineState(ctx, st.scopeKey, ++st.gen);
    } else {
      drawInline();
    }
  }

  /** Legacy tab entry (no-op if standalone #tab-tuning is gone). */
  function render(opts) {
    if (typeof document === "undefined" || !document.getElementById("tunScope")) return;
    if (opts && opts.scope) renderInline({ site: opts.scope.site, equip: opts.scope.equip, ruleId: RL().LIMITS_RULE_ID });
  }

  const exported = {
    FIELDS, unitFor, unitLabel, displayRows, buildOverride, bandChartOption,
    sweepFieldsForRule, assessableSweepRoles, buildRuleOverride, resetSweepOverrideForRule, rollbackSweepOverrideForRule,
    renderInline, render,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  root.ofddTuning = exported;
})(typeof globalThis !== "undefined" ? globalThis : this);
