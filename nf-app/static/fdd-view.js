// FDD tab view model (Full): which rules the selected equipment has, their result status, the summary strip, the
// faults-first order, and the view state kept in the page URL. Pure functions (no DOM), so node tests run them in a vm
// like the other static scripts; app.js renders what they return. Layout only: no rule math lives here.
//
// Statuses (one per rule row):
//   fault         the hook's latest result is a confirmed fault (fault hours > 0)
//   pass          assessed, no fault
//   skipped       the rule did not run here: no run proof, missing inputs, a rule that reads meter data, ...
//   insufficient  ran without enough data: no covered time (equipment off the whole window), stale or missing input data,
//                 or no result written yet
// Needs: model.js (has), fdd.js (equipRules rows passed in).

/** @typedef {{ ruleId: string, equipId: string, rule: any, row: any, result: any, status: string, faultHours: number|null, reason: string }} FddEntry */

const FDD_STATUSES = Object.freeze(["fault", "insufficient", "pass", "skipped"]);
const FDD_STATUS_LABELS = Object.freeze({ fault: "Faults", pass: "Pass", skipped: "Skipped", insufficient: "Insufficient" });

/** A plain-language reason for a result that is not a fault / pass, from the hook's attrs (fddStatus, fddReason). */
function fddPlainReason(attrs = {}, row = null) {
  const reason = String(attrs.fddReason || "");
  if (/^no_run_proof/.test(reason)) return "no run proof: no fan / pump status or command on this equipment or the one feeding it";
  if (attrs.fddStatus === "stale") return "input data is stale (no recent samples)";
  if (/not running|no covered|covered time/i.test(reason)) return "equipment off the whole window (nothing to assess)";
  if (/sensor not assessed/i.test(reason)) return "sensor not assessed (no covered time)";
  if (reason) return reason.replace(/_/g, " ");
  if (row && row.pointInputs === false) return "uses utility / meter data, not points";
  if (row && !row.runnable && row.missing && row.missing.length) return `missing inputs: ${row.missing.join(", ")}`;
  return "";
}

/** Status + fault hours of one rule row on one equipment. `result` = the hook's summary result point (or null). */
function fddEntryOf(row, result) {
  const attrs = (result && result.rec && result.rec.attrs) || {};
  const latest = result ? (result.latest ? (result.latest.double ?? result.latest.real) : null) : null;
  const hoursOut = attrs.fddOutput === "fault_hours" || (result && (result.units === "h" || attrs.unit === "h"));
  const faultHours = latest == null || !Number.isFinite(Number(latest)) ? null
    : hoursOut ? Number(latest) : attrs.fddWindowHours ? Number(latest) * Number(attrs.fddWindowHours) / 100 : null;
  let status;
  if (!row.runnable) status = "skipped";
  else if (!result) status = "insufficient";
  else if (attrs.fddStatus === "not-assessed") status = /^no_run_proof/.test(String(attrs.fddReason || "")) ? "skipped" : "insufficient";
  else if (attrs.fddStatus === "stale") status = "insufficient";
  else if (attrs.fddStatus === "fault" || (latest != null && Number(latest) > 0)) status = "fault";
  else if (latest == null) status = "insufficient";
  else status = "pass";
  const reason = status === "fault" || status === "pass" ? "" : (fddPlainReason(attrs, row) || (result ? "" : "no result written yet"));
  return { ruleId: row.rule.id, equipId: idOf(row.equip), rule: row.rule, row, result, status, faultHours: status === "skipped" ? null : faultHours, reason };
}

/** Faults first (most fault hours first), then insufficient, pass, skipped; ties by rule id. @param {FddEntry[]} entries */
function fddSortEntries(entries) {
  const rank = (s) => FDD_STATUSES.indexOf(s);
  return [...entries].sort((a, b) => rank(a.status) - rank(b.status)
    || (a.status === "fault" ? (b.faultHours ?? 0) - (a.faultHours ?? 0) : 0) || a.ruleId.localeCompare(b.ruleId));
}

/** Counts and fault hours per status for the summary strip. @param {FddEntry[]} entries */
function fddSummary(entries) {
  const out = Object.fromEntries(FDD_STATUSES.map((s) => [s, { count: 0, hours: 0 }]));
  for (const e of entries) {
    out[e.status].count++;
    if (e.faultHours != null && Number.isFinite(e.faultHours)) out[e.status].hours += e.faultHours;
  }
  return out;
}

/**
 * Rows on screen: a chip filter shows that status only; otherwise faults and insufficient rows, with pass and skipped
 * behind "show all". Returns { shown, hidden } (hidden = how many rows "show all" would add).
 * @param {FddEntry[]} entries @param {{ filter?: string, showAll?: boolean }} [o]
 */
function fddVisibleEntries(entries, { filter = "", showAll = false } = {}) {
  const sorted = fddSortEntries(entries);
  if (filter && FDD_STATUSES.includes(filter)) return { shown: sorted.filter((e) => e.status === filter), hidden: 0 };
  const collapsed = (e) => e.status === "pass" || e.status === "skipped";
  return { shown: showAll ? sorted : sorted.filter((e) => !collapsed(e)), hidden: showAll ? 0 : sorted.filter(collapsed).length };
}

/** View state in the page URL (with the range keys charts.js keeps there): ?fdd.equip=&fdd.rule=&fdd.filter= */
function fddUrlState(search = typeof location === "undefined" ? "" : location.search) {
  const q = new URLSearchParams(search);
  const filter = q.get("fdd.filter") || "";
  return { equip: q.get("fdd.equip") || "", rule: q.get("fdd.rule") || "", filter: FDD_STATUSES.includes(filter) ? filter : "" };
}
/** The URL with this view state written (empty values removed). */
function fddUrlWith(href, { equip = "", rule = "", filter = "" } = {}) {
  const url = new URL(href);
  for (const [k, v] of [["fdd.equip", equip], ["fdd.rule", rule], ["fdd.filter", filter]]) {
    if (v) url.searchParams.set(k, v); else url.searchParams.delete(k);
  }
  return url.toString();
}

/**
 * The rule's shipped SI thresholds for the expanded row (the tuner drawer shows and edits this site's values): one entry per
 * tuning control (label, SI value, SI unit) from the plot-spec rule_tuning templates, else the catalog's raw parameters.
 * @param {any} rule catalog rule @param {Record<string, any>|null} [controls] plot-spec rule_tuning.rules[id].controls
 */
function fddSiParameters(rule, controls = null) {
  const units = { degC: "°C", "degC/h": "°C/h", delta_degC: "K", frac: "(fraction 0-1)", pct: "%", L_per_s: "L/s", Pa: "Pa", min: "min", s: "s", h: "h" };
  if (controls && Object.keys(controls).length) {
    return Object.values(controls).filter((c) => typeof c.default === "number")
      .map((c) => ({ name: c.label || c.key, key: c.key, value: Number(c.default.toFixed(4)), unit: units[c.unit] ?? (c.unit || "") }));
  }
  const p = (rule && rule.parameters) || {};
  return Object.entries(p).filter(([, v]) => typeof v === "number").map(([k, v]) => ({ name: k, key: k, value: Number(v.toFixed(4)), unit: "" }));
}