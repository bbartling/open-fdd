// Overview occupancy calendar editor (Full edition). Uses the tuning hook's OCC-CALENDAR document, revision-checked,
// per site. No NF schedules or BACnet writes. A failed GET leaves editing disabled (never silently overwrite a saved
// calendar). Draft changes immediately redraw the weekly reference line; Save persists the whole document atomically.
(function (root) {
  "use strict";
  const states = new Map();
  let generation = 0;
  root.ofddOccCalendars = root.ofddOccCalendars || {};
  const O = () => root.ofddOccupancy;
  const ZB = () => root.ofddZoneBand;
  // the slider follows the header units button (units.js, localStorage "openfdd-units"); imperial is display only
  const system = () => (root.ofddUnits ? root.ofddUnits.displaySystem() : "si");
  const SVG = "http://www.w3.org/2000/svg";
  const node = (tag, text, attrs = {}) => {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    for (const [k, v] of Object.entries(attrs)) e[k] = v;
    return e;
  };
  async function render({ site, timezone, onChange }) {
    const host = document.getElementById("overviewOccupancy");
    if (!host || !O()) return;
    const gen = ++generation;
    host.hidden = !site;
    if (!site) return;
    if (!states.has(site)) {
      host.textContent = "Loading occupancy calendar…";
      try {
        const answer = await root.ofddTuning.callHook({ action: "get", site, scope: "site", rule_id: O().RULE_ID });
        if (!answer.ok) throw new Error(answer.error || "calendar unavailable");
        const saved = answer.source === "saved";
        // an unsaved default starts in the site's own zone; a saved calendar keeps the zone it was saved with
        const calendar = saved ? O().normalizeCalendar(answer.calendar, { tz: timezone }) : O().defaultCalendar(timezone);
        // a newer render (the user left and came back) owns the shared state: drop this older answer
        if (gen !== generation || states.has(site)) return;
        states.set(site, { calendar, saved: saved ? JSON.stringify(calendar) : "", revision: answer.active?.site?.revision || 0, error: "", saveError: "", busy: false, stored: saved, view: null });
        // only a SAVED calendar drives the charts; until then they keep the site's NF schedule (or the 4.x default)
        if (saved) root.ofddOccCalendars[site] = calendar;
        else delete root.ofddOccCalendars[site];
      } catch (e) {
        if (gen !== generation) return;
        host.replaceChildren(node("h3", "Weekly occupancy calendar"), node("p", `Read only: ${e.message || e}`, { className: "hint", role: "status" }));
        const retry = node("button", "Retry", { type: "button", className: "btn" });
        retry.addEventListener("click", () => render({ site, timezone, onChange }));
        host.append(retry);
        return;
      }
    }
    if (gen !== generation) return;
    const st = states.get(site);
    const details = node("details", null, { className: "occ-editor" });
    const sum = node("summary", "Weekly occupancy calendar");
    const hours = node("strong", "", { id: "occHours" });
    const note = node("p", "Times are local to the site. An end at or before start wraps past midnight. Edits update the weekly reference line live; Save stores this site’s calendar.", { className: "hint" });
    const zoneLabel = node("label", "Site timezone ");
    const zone = node("input", null, { type: "text", value: st.calendar.timezone, id: "occTimezone", required: true });
    zoneLabel.append(zone);
    const table = node("table");
    const head = node("thead"), tr = node("tr");
    for (const h of ["Day", "Occupied", "Start", "End"]) tr.append(node("th", h));
    head.append(tr); table.append(head);
    const body = node("tbody"), inputs = new Map();
    for (const d of O().DAYS) {
      const row = node("tr"); row.append(node("th", O().DAY_LABELS[d]));
      const controls = {};
      for (const [key, type] of [["occupied", "checkbox"], ["start", "time"], ["end", "time"]]) {
        const td = node("td"), input = node("input", null, { type, id: `occ-${d}-${key}` });
        input.setAttribute("aria-label", `${O().DAY_LABELS[d]} ${key}`);
        if (type === "checkbox") input.checked = st.calendar.days[d].occupied;
        else input.value = st.calendar.days[d][key];
        controls[key === "occupancy_status" ? "occupied" : key] = input; td.append(input); row.append(td);   // the checkbox is c.occupied below (its element id keeps the occupancy_status name)
      }
      inputs.set(d, controls); body.append(row);
    }
    table.append(body);
    const status = node("span", "", { className: "hint", role: "status", id: "occStatus" });
    const save = node("button", "Save occupancy calendar", { type: "button", className: "btn", id: "occSave" });
    const reset = node("button", "Use default (60 h/week)", { type: "button", className: "btn", id: "occDefault" });
    const redraw = () => { if (onChange) Promise.resolve(onChange()).catch(() => {}); };
    // ---- occupied zone temperature range (5.0.22): a low / high slider saved with the calendar, stored in degC ----
    const sys = system(), spec = ZB().sliderSpec(sys);
    const zbPanel = node("section", null, { className: "zone-band", id: "zoneBand" });
    const zbReadout = node("strong", "", { id: "zbReadout", role: "status" });
    const mkRange = (id, label) => {
      const i = node("input", null, { type: "range", id, className: "zb-range" });
      i.min = String(spec.min); i.max = String(spec.max); i.step = String(spec.step);
      i.setAttribute("aria-label", label);
      return i;
    };
    const zbLo = mkRange("zbLo", `Zone temperature low (${spec.unit})`), zbHi = mkRange("zbHi", `Zone temperature high (${spec.unit})`);
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "zb-track"); svg.setAttribute("viewBox", "0 0 100 6"); svg.setAttribute("preserveAspectRatio", "none"); svg.setAttribute("aria-hidden", "true");
    const rail = document.createElementNS(SVG, "rect"), fill = document.createElementNS(SVG, "rect");
    rail.setAttribute("class", "zb-rail"); fill.setAttribute("class", "zb-fill");
    for (const r of [rail, fill]) { r.setAttribute("y", "2"); r.setAttribute("height", "2"); r.setAttribute("rx", "1"); }
    rail.setAttribute("x", "0"); rail.setAttribute("width", "100");
    svg.append(rail, fill);
    const zbScale = node("div", null, { className: "zb-scale" });
    zbScale.append(node("span", `${spec.min.toFixed(spec.decimals)} ${spec.unit}`), node("span", `${spec.max.toFixed(spec.decimals)} ${spec.unit}`));
    const zbDefault = node("button", `Use default (${ZB().describe(ZB().defaultBand(), sys)})`, { type: "button", className: "btn", id: "zbDefault" });
    const zbSave = node("button", "Save zone range", { type: "button", className: "btn", id: "zbSave" });
    const zbStatus = node("span", "", { className: "hint", role: "status", id: "zbStatus" });
    const slider = node("div", null, { className: "zb-slider" });
    slider.append(svg, zbLo, zbHi);
    zbPanel.append(node("h3", "Occupied zone temperature range"),
      node("p", `The comfort band for the zone comfort analytics and the zone comfort FDD rules (VAV-1 comfort, SCHED-1) while the building is occupied. Limits ${ZB().describe({ lo_c: ZB().LIMIT_LO_C, hi_c: ZB().LIMIT_HI_C }, sys)}; the handles stay at least ${spec.gapLabel} apart. A rule tuned on its own keeps its own values. Stored in °C; the units button changes only what you see.`, { className: "hint" }),
      zbReadout, slider, zbScale, zbSave, zbDefault, zbStatus);
    const bandNow = () => ZB().resolveBand(st.calendar.zone_band);
    const pct = (c) => Math.max(0, Math.min(100, ((ZB().toDisplay(c, sys) - spec.min) / (spec.max - spec.min)) * 100));
    const shown = (c) => String(+ZB().toDisplay(c, sys).toFixed(spec.decimals));
    const drawBand = () => {
      const b = bandNow();
      zbLo.value = shown(b.lo_c); zbHi.value = shown(b.hi_c);
      fill.setAttribute("x", pct(b.lo_c).toFixed(2)); fill.setAttribute("width", Math.max(0, pct(b.hi_c) - pct(b.lo_c)).toFixed(2));
      zbReadout.textContent = `Low ${shown(b.lo_c)} ${spec.unit} · High ${shown(b.hi_c)} ${spec.unit} · ${b.source === "saved" ? "custom" : "default"}`;
    };
    const moveBand = (which, input, commit) => {
      const next = ZB().moveHandle(bandNow(), which, ZB().fromDisplay(Number(input.value), sys));
      st.calendar = { ...st.calendar, zone_band: { lo_c: next.lo_c, hi_c: next.hi_c } };
      st.touched = true; st.error = ""; st.saveError = "";
      root.ofddOccCalendars[site] = st.calendar;
      drawBand(); drawState();
      if (commit) redraw();            // the charts preview the band when the handle is released
    };
    zbLo.addEventListener("input", () => moveBand("lo", zbLo, false));
    zbHi.addEventListener("input", () => moveBand("hi", zbHi, false));
    zbLo.addEventListener("change", () => moveBand("lo", zbLo, true));
    zbHi.addEventListener("change", () => moveBand("hi", zbHi, true));
    zbDefault.addEventListener("click", () => {
      const d = ZB().defaultBand();
      st.calendar = { ...st.calendar, zone_band: { lo_c: d.lo_c, hi_c: d.hi_c } };
      st.touched = true; root.ofddOccCalendars[site] = st.calendar; drawBand(); drawState(); redraw();
    });
    const update = () => {
      try {
        const days = {};
        for (const [d, c] of inputs) days[d] = { occupied: c.occupied.checked, start: c.start.value, end: c.end.value };
        st.calendar = O().normalizeCalendar({ timezone: zone.value, days, zone_band: st.calendar.zone_band });
        st.touched = true;
        root.ofddOccCalendars[site] = st.calendar;
        st.error = ""; st.saveError = "";
        redraw();
      } catch (e) { st.error = e.message || String(e); }
      drawState();
    };
    const drawState = () => {
      if (!save.isConnected) return;
      const h = O().occupiedHoursPerWeek(st.calendar);
      hours.textContent = `Bare-min occupied hours/week: ${h}`;
      const dirty = JSON.stringify(st.calendar) !== st.saved;
      save.textContent = st.stored ? "Save occupancy calendar" : "Save and use this calendar";
      status.textContent = st.error || st.saveError || (st.busy ? "Saving…" : !st.stored && !st.touched
        ? "Not saved yet: the weekly charts use the site's NF schedule, else the 4.x default (50 h/week), until you save"
        : dirty ? "Unsaved changes (the charts preview them)" : `Saved (revision ${st.revision})`);
      // a failed Save keeps the draft and leaves Save enabled to retry; only an invalid draft disables it
      save.disabled = st.busy || !!st.error || (!dirty && !st.saveError);
      zbSave.disabled = save.disabled; zbDefault.disabled = st.busy; zbLo.disabled = st.busy; zbHi.disabled = st.busy;
      zbStatus.textContent = status.textContent;
      reset.disabled = st.busy;
      zone.disabled = st.busy;
      for (const c of inputs.values()) {
        c.occupied.disabled = st.busy;
        c.start.disabled = st.busy || !c.occupied.checked;
        c.end.disabled = st.busy || !c.occupied.checked;
      }
    };
    zone.addEventListener("input", update);
    for (const c of inputs.values()) for (const input of Object.values(c)) input.addEventListener("input", update);
    reset.addEventListener("click", () => {
      const cal = O().defaultCalendar(zone.value);
      for (const [d, c] of inputs) { c.occupied.checked = cal.days[d].occupied; c.start.value = cal.days[d].start; c.end.value = cal.days[d].end; }
      zone.value = cal.timezone; update();
    });
    const doSave = async () => {
      st.busy = true; drawState();
      try {
        const ans = await root.ofddTuning.callHook({ action: "save", site, scope: "site", rule_id: O().RULE_ID,
          expected_revision: st.revision, overrides: { version: 1, calendar: st.calendar } });
        if (!ans.ok) throw new Error(ans.error || "Save failed");
        st.calendar = O().normalizeCalendar(ans.calendar);
        st.saved = JSON.stringify(st.calendar); st.revision = ans.revision; st.saveError = ""; st.stored = true;
        root.ofddOccCalendars[site] = st.calendar; redraw();
      } catch (e) { st.saveError = `Not saved: ${e.message || e} (your changes are kept; Save to retry)`; }
      // the editor on screen may be a newer render of this site (a theme change during Save): refresh that one
      finally { st.busy = false; if (st.view) st.view(); }
    };
    save.addEventListener("click", doSave);
    zbSave.addEventListener("click", doSave);     // one document: the calendar and its zone range save together
    details.append(sum, hours, note, zoneLabel, table, save, reset, status);
    st.view = () => { drawBand(); drawState(); };
    host.replaceChildren(zbPanel, details); drawBand(); drawState();
  }
  root.ofddOccupancyEditor = { render };
})(typeof globalThis !== "undefined" ? globalThis : this);