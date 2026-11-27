// Run proof (#1608): is the equipment a rule judges proven running? Twin of open_fdd/run_proof.py, same contract
// (fdd-catalog.json -> operating_status, built from sql/fdd/run_proof.json). Nothing here reads a point name: everything comes
// from the model (roles bound by NF class / markers, refs on the equipment records).
//
// Resolution, first hit wins:
//   1. the equipment's own proof: a bound status role, then a bound command role (order of `own` in the contract);
//   2. the proof of the equipment that FEEDS it, one hop: its airRef / chilledWaterRef / hotWaterRef target, then an
//      isFedBy target, then any equipment that lists it under `feeds` (RDF: brick:isFedBy / brick:feeds). Each feeder is
//      judged by its own proof (tier 1);
//   3. a VAV with no airRef at all, when the site has exactly one AHU-class equipment: that AHU's own proof
//      (via `assumedSingleAhu`). A dangling airRef is not guessed around. Off when assumeSingleFeeder is false.
//   4. none -> a gated rule is SKIPPED with reason `no_run_proof`, never a silent PASS.
// Needs model.js (idOf) and fdd.js (bindRoles, equipPool, equipKinds). The FDD hook loads it in the same sandbox as those two.

/** Ref value -> bare id ("@AHU-1" and "AHU-1" are the same). */
const runProofRefId = (v) => String(v ?? "").trim().replace(/^@/, "");

/** Comma list or array -> bare ids. */
const runProofList = (v) => (Array.isArray(v) ? v : String(v ?? "").split(",")).map(runProofRefId).filter(Boolean);

/** Names a ref may use for an equip record: its id, name, NF uuid, display name. */
const runProofNames = (rec) => new Set([idOf(rec), rec.name, rec.uuid, (rec.attrs || {}).dis].filter(Boolean).map(runProofRefId));

const RUN_PROOF_PERCENT = /^(%|percent|pct)$/i;
const RUN_PROOF_FRACTION = /^(ratio|fraction|frac|0-1|0\.\.1|0 to 1|unitless ratio)$/i;
const RUN_PROOF_START_STOP = /(^|[-_ ])(run|enable|enabled|start|stop|startstop|onoff|on-off)([-_ ]|$)/i;
const RUN_PROOF_ANALOG = /(^|[-_ ])(speed|vfd|freq|frequency|position|pos|output|signal)([-_ ]|$)/i;

/**
 * #1631: can this COMMAND point be the run proof? The proof is judged against a 0-1 threshold, so the command's scale
 * must be known. Usable: a boolean point; a percent or 0-1 fraction unit; a start/stop (run / enable) command, which is
 * 0/1 even when the model leaves `kind` unset. Refused: a numeric analog command (speed, VFD, position ...) with no
 * percent or fraction unit, whose 0-100 or 0-1 scale cannot be told apart. '' when usable, else the reason.
 * @returns {string}
 */
function runProofCommandProblem(point) {
  if (!point) return "no point";
  if (/^bool/i.test(String(point.kind || ""))) return "";
  const unit = String(point.units || "").trim();
  if (RUN_PROOF_PERCENT.test(unit) || RUN_PROOF_FRACTION.test(unit)) return "";
  const words = [point.cls || "", ...(point.tags || [])].join(" ");
  if (RUN_PROOF_START_STOP.test(words) && !RUN_PROOF_ANALOG.test(words)) return "";
  return unit ? `command ${point.name || point.uuid} has unit "${unit}", not a percent or 0-1 fraction`
    : `command ${point.name || point.uuid} is an analog output with no unit (0-100 or 0-1 cannot be told apart)`;
}

/** The equip's OWN proof: { source: "status" | "command", role, point } or null. Every bound point of a role is a
 * candidate, in contract order; a command whose scale is unknown is skipped (#1631) and listed in `refused`. */
/** @returns {{ source: string, role: string, point: any } | null} */
function ownRunProof(equipRec, model, catalog, refused = []) {
  const own = catalog.operating_status.own;
  const roles = [...own.status, ...own.command];
  const bound = bindRoles(roles, equipPool(equipRec, model), catalog);
  for (const source of ["status", "command"]) {
    for (const role of own[source]) {
      for (const point of bound[role] || []) {
        const why = source === "command" ? runProofCommandProblem(point) : "";
        if (!why) return { source, role, point };
        refused.push({ equip: idOf(equipRec), role, point: point.name || point.uuid, reason: why });
      }
    }
  }
  return null;
}

/**
 * The site's only AHU, when this equip is a VAV with no airRef at all. Null when airRef is set (even if it
 * points nowhere), when the site has zero or several AHU-class equips, or when the equip is not a VAV.
 * @returns {any | null}
 */
function singleAhuRecord(equipRec, model, catalog) {
  if (!equipKinds(equipRec, catalog).includes("vav")) return null;
  if (runProofRefId((equipRec.attrs || {}).airRef)) return null;
  const site = (equipRec.attrs || {}).siteRef || "";
  const ahus = model.equips.filter((e) => e !== equipRec && ((e.attrs || {}).siteRef || "") === site && equipKinds(e, catalog).includes("ahu"));
  return ahus.length === 1 ? ahus[0] : null;
}

/** App option assumeSingleFeeder (default on, matching the RCx "AHU on" assumption). The hook passes the option explicitly. */
function assumeSingleFeederOn() {
  if (typeof siteAssumeSingleFeeder === "function") return siteAssumeSingleFeeder() !== false;
  return true;
}

/** Candidate feeders of an equip, in contract order: [{ rec, via }]. Same site only, never itself. */
function runProofFeeders(equipRec, model, catalog) {
  const a = equipRec.attrs || {};
  const site = a.siteRef || "";
  const siteEquips = model.equips.filter((e) => ((e.attrs || {}).siteRef || "") === site);
  const pool = siteEquips.filter((e) => e !== equipRec);
  const find = (target) => {
    const t = runProofRefId(target);
    // count across the whole site, the requester included: an ambiguous ref binds nothing (never guess), and a ref
    // that names the requester itself is not a feeder
    const hits = t ? siteEquips.filter((e) => runProofNames(e).has(t)) : [];
    return hits.length === 1 && hits[0] !== equipRec ? hits : [];
  };
  const out = [];
  for (const ref of catalog.operating_status.feeders.refs) for (const rec of find(a[ref])) out.push({ rec, via: ref });
  for (const target of runProofList(a.isFedBy)) for (const rec of find(target)) out.push({ rec, via: "isFedBy" });
  const mine = runProofNames(equipRec);
  for (const rec of pool) if (runProofList((rec.attrs || {}).feeds).some((x) => mine.has(x))) out.push({ rec, via: "feeds" });
  return out;
}

/**
 * The run proof of one equip.
 * @returns {{ found: boolean, tier?: string, source?: string, role?: string, point?: any,
 *             equip?: string, via?: string, assumed?: boolean, reason?: string,
 *             refused?: Array<{ equip: string, role: string, point: string, reason: string }> }}
 */
function resolveRunProof(equipRec, model, catalog, opts = {}) {
  const refused = [];   // commands skipped for an unknown scale (#1631); the next candidate wins
  const assume = opts.assumeSingleFeeder !== undefined ? opts.assumeSingleFeeder !== false : assumeSingleFeederOn();
  const own = ownRunProof(equipRec, model, catalog, refused);
  if (own) return { found: true, tier: "own", source: own.source, role: own.role, point: own.point, equip: idOf(equipRec), via: "self", refused };
  for (const { rec, via } of runProofFeeders(equipRec, model, catalog)) {
    const hit = ownRunProof(rec, model, catalog, refused);
    if (hit) return { found: true, tier: "feeder", source: hit.source, role: hit.role, point: hit.point, equip: idOf(rec), via, refused };
  }
  if (assume) {
    const ahu = singleAhuRecord(equipRec, model, catalog);
    if (ahu) {
      const hit = ownRunProof(ahu, model, catalog, refused);
      if (hit) return { found: true, tier: "feeder", source: hit.source, role: hit.role, point: hit.point, equip: idOf(ahu), via: "assumedSingleAhu", assumed: true, refused };
    }
  }
  return { found: false, reason: catalog.operating_status.skip_reason, refused };
}
