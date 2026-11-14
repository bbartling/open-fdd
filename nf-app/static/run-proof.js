// Run proof (#1608): is the equipment a rule judges proven running? Twin of open_fdd/run_proof.py, same contract
// (fdd-catalog.json -> run_proof, built from sql/fdd/run_proof.json). Nothing here reads a point name: everything comes
// from the model (roles bound by NF class / markers, refs on the equipment records).
//
// Resolution, first hit wins:
//   1. the equipment's own proof: a bound status role, then a bound command role (order of `own` in the contract);
//   2. the proof of the equipment that FEEDS it, one hop: its airRef / chilledWaterRef / hotWaterRef target, then an
//      isFedBy target, then any equipment that lists it under `feeds` (RDF: brick:isFedBy / brick:feeds). Each feeder is
//      judged by its own proof (tier 1);
//   3. none -> a gated rule is SKIPPED with reason `no_run_proof`, never a silent PASS.
// Needs model.js (idOf) and fdd.js (bindRoles, equipPool). The FDD hook loads it in the same sandbox as those two.

/** Ref value -> bare id ("@AHU-1" and "AHU-1" are the same). */
const runProofRefId = (v) => String(v ?? "").trim().replace(/^@/, "");

/** Comma list or array -> bare ids. */
const runProofList = (v) => (Array.isArray(v) ? v : String(v ?? "").split(",")).map(runProofRefId).filter(Boolean);

/** Names a ref may use for an equip record: its id, name, NF uuid, display name. */
const runProofNames = (rec) => new Set([idOf(rec), rec.name, rec.uuid, (rec.attrs || {}).dis].filter(Boolean).map(runProofRefId));

/** The equip's OWN proof: { source: "status" | "command", role, point } or null. */
/** @returns {{ source: string, role: string, point: any } | null} */
function ownRunProof(equipRec, model, catalog) {
  const own = catalog.run_proof.own;
  const roles = [...own.status, ...own.command];
  const bound = bindRoles(roles, equipPool(equipRec, model), catalog);
  for (const source of ["status", "command"]) {
    for (const role of own[source]) if (bound[role] && bound[role].length) return { source, role, point: bound[role][0] };
  }
  return null;
}

/** Candidate feeders of an equip, in contract order: [{ rec, via }]. Same site only, never itself. */
function runProofFeeders(equipRec, model, catalog) {
  const a = equipRec.attrs || {};
  const site = a.siteRef || "";
  const pool = model.equips.filter((e) => e !== equipRec && ((e.attrs || {}).siteRef || "") === site);
  const find = (target) => {
    const t = runProofRefId(target);
    const hits = t ? pool.filter((e) => runProofNames(e).has(t)) : [];
    return hits.length === 1 ? hits : [];   // an ambiguous ref (one name, several equipment) binds nothing: never guess
  };
  const out = [];
  for (const ref of catalog.run_proof.feeders.refs) for (const rec of find(a[ref])) out.push({ rec, via: ref });
  for (const target of runProofList(a.isFedBy)) for (const rec of find(target)) out.push({ rec, via: "isFedBy" });
  const mine = runProofNames(equipRec);
  for (const rec of pool) if (runProofList((rec.attrs || {}).feeds).some((x) => mine.has(x))) out.push({ rec, via: "feeds" });
  return out;
}

/**
 * The run proof of one equip.
 * @returns {{ found: boolean, tier?: string, source?: string, role?: string, point?: any,
 *             equip?: string, via?: string, reason?: string }}
 */
function resolveRunProof(equipRec, model, catalog) {
  const own = ownRunProof(equipRec, model, catalog);
  if (own) return { found: true, tier: "own", source: own.source, role: own.role, point: own.point, equip: idOf(equipRec), via: "self" };
  for (const { rec, via } of runProofFeeders(equipRec, model, catalog)) {
    const hit = ownRunProof(rec, model, catalog);
    if (hit) return { found: true, tier: "feeder", source: hit.source, role: hit.role, point: hit.point, equip: idOf(rec), via };
  }
  return { found: false, reason: catalog.run_proof.skip_reason };
}
