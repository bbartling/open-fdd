// Overview occupancy calendar editor (Full edition). Uses the tuning hook's OCC-CALENDAR document, revision-checked,
// per site. No NF schedules or BACnet writes. A failed GET leaves editing disabled (never silently overwrite a saved
// calendar). Draft changes immediately redraw the weekly reference line; Save persists the whole document atomically.
(function (root) {
  "use strict";
  const states = new Map();
  let generation = 0;
  root.ofddOccCalendars = root.ofddOccCalendars || {};
  const O = () => root.ofddOccupancy;
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
        const calendar = O().normalizeCalendar(answer.calendar, { tz: timezone });
        const saved = answer.source === "saved";
        states.set(site, { calendar, saved: saved ? JSON.stringify(calendar) : "", revision: answer.active?.site?.revision || 0, error: "", busy: false, stored: saved });
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
        controls[key] = input; td.append(input); row.append(td);
      }
      inputs.set(d, controls); body.append(row);
    }
    table.append(body);
    const status = node("span", "", { className: "hint", role: "status", id: "occStatus" });
    const save = node("button", "Save occupancy calendar", { type: "button", className: "btn", id: "occSave" });
    const reset = node("button", "Use default (60 h/week)", { type: "button", className: "btn", id: "occDefault" });
    const redraw = () => { if (onChange) Promise.resolve(onChange()).catch(() => {}); };
    const update = () => {
      try {
        const days = {};
        for (const [d, c] of inputs) days[d] = { occupied: c.occupied.checked, start: c.start.value, end: c.end.value };
        st.calendar = O().normalizeCalendar({ timezone: zone.value, days });
        st.touched = true;
        root.ofddOccCalendars[site] = st.calendar;
        st.error = "";
        redraw();
      } catch (e) { st.error = e.message || String(e); }
      drawState();
    };
    const drawState = () => {
      const h = O().occupiedHoursPerWeek(st.calendar);
      hours.textContent = `Bare-min occupied hours/week: ${h}`;
      const dirty = JSON.stringify(st.calendar) !== st.saved;
      save.textContent = st.stored ? "Save occupancy calendar" : "Save and use this calendar";
      status.textContent = st.error || (st.busy ? "Saving…" : !st.stored && !st.touched
        ? "Not saved yet: the weekly charts use the site's NF schedule, else the 4.x default (50 h/week), until you save"
        : dirty ? "Unsaved changes (the charts preview them)" : `Saved (revision ${st.revision})`);
      save.disabled = st.busy || !!st.error || !dirty;
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
    save.addEventListener("click", async () => {
      st.busy = true; drawState();
      try {
        const ans = await root.ofddTuning.callHook({ action: "save", site, scope: "site", rule_id: O().RULE_ID,
          expected_revision: st.revision, overrides: { version: 1, calendar: st.calendar } });
        if (!ans.ok) throw new Error(ans.error || "Save failed");
        st.calendar = O().normalizeCalendar(ans.calendar);
        st.saved = JSON.stringify(st.calendar); st.revision = ans.revision; st.error = ""; st.stored = true;
        root.ofddOccCalendars[site] = st.calendar; redraw();
      } catch (e) { st.error = `Not saved: ${e.message || e}`; }
      finally { st.busy = false; if (gen === generation) drawState(); }
    });
    details.append(sum, hours, note, zoneLabel, table, save, reset, status);
    host.replaceChildren(details); drawState();
  }
  root.ofddOccupancyEditor = { render };
})(typeof globalThis !== "undefined" ? globalThis : this);