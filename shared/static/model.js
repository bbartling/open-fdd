// Haystack model for the Open-FDD pages (both editions; source: shared/static/model.js). Every tab renders from the object
// loadModel() returns — nothing site-specific lives in the UI code.
//
//   model layer   SITE / EQUIPMENT / DEVICE records (ids, siteRef, equipRef, markers)
//   default layer every point on each site (siteRef), merged tags + latestValue
//
// Needs nf.js (api, queryAll, field) loaded first.

// Markers every point carries; left out of display labels.
const GENERIC = new Set(["point", "his", "cur", "writable"]);
const has = (p, ...m) => m.every((x) => p.tags.includes(x));
const isTemp = (p) => has(p, "temp");
const isRH = (p) => has(p, "humidity");
const idOf = (r) => (r.attrs || {}).id || r.name;
const markersOf = (r) => ((r.attrs || {}).markers || "").split(",").filter(Boolean);
const ENTITY_TYPES = ["SITE", "EQUIPMENT", "DEVICE"];

/** Haystack ref text, without a leading @. */
function refId(v) {
  return String(v == null ? "" : v).trim().replace(/^@/, "");
}

function pointAttrs(p) {
  if (!p) return {};
  if (p.rec && p.rec.attrs) return p.rec.attrs;
  return p.attrs || {};
}

function pointMarkers(p) {
  if (p && Array.isArray(p.tags)) return p.tags;
  return markersOf(p || {});
}

/**
 * Fault, FDD-result and fault-timeline points. They stay in the model and in Turtle.
 * Overview lists and the visual model (tree, unclassified checks) omit them.
 */
function isDiagnosticPoint(p) {
  if (!p) return false;
  const tags = pointMarkers(p);
  if (tags.some((t) => t === "fault" || t === "fdd" || t === "fault_timeline" || t === "timeline" || /timeline/i.test(String(t)))) return true;
  const a = pointAttrs(p);
  if (a.ruleRef || a.fddOutput || a.fddKind || a.fddTimelineOf) return true;
  const type = String(a.type || "");
  return type === "fdd-result" || type === "fdd-fault-timeline";
}

/** Ids a device equipRef or a point equipRef may use for this equipment record. */
function equipKeys(equip) {
  const a = (equip && equip.attrs) || {};
  return [a.id, equip && equip.name, equip && equip.uuid, a.uuid].map(refId).filter(Boolean);
}

function pointRef(p, key) {
  if (!p) return "";
  if (p[key]) return refId(p[key]);
  return refId(pointAttrs(p)[key]);
}

/**
 * DEVICE records under this equipment, plus a synthetic node for a deviceRef that has no record.
 * A device matches when its equipRef is this equipment's id, name or uuid, or a point on the
 * equipment names it. Orphan devices (equipRef that does not match, or only a point deviceRef)
 * still appear.
 * @returns {{rec: object, synthetic: boolean}[]}
 */
function devicesForEquip(equip, devices, points) {
  const keys = new Set(equipKeys(equip));
  const onEquip = (points || []).filter((p) => keys.has(pointRef(p, "equipRef")));
  const wanted = new Set();
  const out = [];
  for (const d of devices || []) {
    const did = refId(idOf(d));
    const byEquip = keys.has(refId((d.attrs || {}).equipRef));
    const byPoint = !!did && onEquip.some((p) => pointRef(p, "deviceRef") === did);
    if (!byEquip && !byPoint) continue;
    if (did) wanted.add(did);
    out.push({ rec: d, synthetic: false });
  }
  for (const p of onEquip) {
    const did = pointRef(p, "deviceRef");
    if (!did || wanted.has(did)) continue;
    wanted.add(did);
    out.push({ rec: { name: did, pointType: "DEVICE", attrs: { id: did, dis: did, markers: "device" } }, synthetic: true });
  }
  return out;
}

/** DEVICE records, including a device marker that NF did not store as pointType DEVICE. */
function isDeviceRecord(r) {
  const t = String((r && r.pointType) || "").toUpperCase();
  if (t === "DEVICE") return true;
  const tags = markersOf(r || {});
  return tags.includes("device") && !tags.includes("point") && t !== "SITE" && t !== "EQUIPMENT" && t !== "POINT";
}

/** @param {NfRecord} r @returns {OfddPoint} */
function toPoint(r) {
  const a = r.attrs || {};
  const tags = markersOf(r);
  return {
    uuid: r.uuid, tags, dis: a.dis || r.name, units: a.unit || "", kind: a.kind || "Number",
    name: tags.filter((t) => !GENERIC.has(t) && t !== "sensor").join(" ") || r.name,
    equipRef: a.equipRef || "", weatherStationRef: a.weatherStationRef || "", siteRef: a.siteRef || "",
    deviceRef: a.deviceRef || "", objectId: a.object_id || "", bacnet: a.bacnet_object || "",
    cls: a.class || "", latest: r.latestValue, rec: r,
  };
}

/** Whole site model: entity records plus every point on every modeled site. */
/** @returns {Promise<OfddModel>} */
async function loadModel() {
  const recs = await queryAll({ layer: "model" });
  const of = (t) => recs.filter((r) => r.pointType === t);
  /** @type {OfddModel} */
  const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: recs.filter(isDeviceRecord), points: [] };
  if (!model.sites.length) {
    throw new Error("no Haystack site in this NF's model layer; tag the site, equipment and points first");
  }
  const noteSites = /** @type {any} */ (globalThis).noteModelSiteCount;
  if (typeof noteSites === "function") noteSites(model.sites.length);
  model.points = await loadPoints(model);
  return model;
}

/** Points for every site in the model (cheap enough to re-run on the live loop). */
/** @param {OfddModel} model @returns {Promise<OfddPoint[]>} */
async function loadPoints(model) {
  const pages = await Promise.all(model.sites.map((s) =>
    queryAll({ layer: "default", structuredQuery: field("siteRef", idOf(s)) })));
  return pages.flat().filter((r) => !ENTITY_TYPES.includes(r.pointType)).map(toPoint);
}

// ---- RDF (Turtle) export ----------------------------------------------------------
// Haystack 4.0.0 is the overlay. 223P is the rule-input contract (roles/openfdd-roles.json);
// this export does not embed 223P. Def IRIs are the published versioned form
// (https://project-haystack.org/def/<lib>/4.0.0#<name>). Markers outside the lists below
// are written under the local namespace and reported as non-standard.
const HAYSTACK_DEFS = "4.0.0";
const HS_NS = {
  ph: `https://project-haystack.org/def/ph/${HAYSTACK_DEFS}#`,
  phScience: `https://project-haystack.org/def/phScience/${HAYSTACK_DEFS}#`,
  phIoT: `https://project-haystack.org/def/phIoT/${HAYSTACK_DEFS}#`,
  phIct: `https://project-haystack.org/def/phIct/${HAYSTACK_DEFS}#`,
  ref: "https://brickschema.org/schema/Brick/ref#",
  brick: "https://brickschema.org/schema/Brick#",
  schema: "https://schema.org/",
};
const TAG_LIB = {
  phScience: ["air", "water", "temp", "humidity", "pressure", "dewPoint", "co2", "flow", "enthalpy", "concentration"],
  phIct: ["device", "controller", "network", "bacnet", "modbus"],
  phIoT: [
    "site", "space", "equip", "point", "sensor", "cmd", "sp", "his", "cur", "writable",
    "discharge", "outside", "zone", "return", "mixed", "exhaust", "inlet", "economizer",
    "damper_position", "fan", "run", "heat", "cool", "stage", "valve", "enable", "occ", "unocc",
    "ahu", "fcu", "vav", "weather", "weatherStation", "elec", "meter", "chilled", "hot",
    "plant", "boiler", "chiller", "hot-water-plant", "chilled-water-plant", "steam-plant",
  ],
};
const TAG_NS = Object.fromEntries(Object.entries(TAG_LIB).flatMap(([ns, tags]) => tags.map((t) => [t, ns])));

const ttlStr = (s) => `"${String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n")}"`;
const ttlId = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, "_");

/**
 * Base IRI of the model's Turtle (#1773): the fixed `urn:nf:`, so a subject is `urn:nf:<NF uuid>` (uuids are globally
 * unique). It depends neither on the host the model was read through (before, location.host, a LAN / VPN IP, a proxy
 * name or the hook's 127.0.0.1 each gave other subjects) nor on the sites, so adding a site never rewrites a subject.
 * The Model & RDF tab, the SPARQL tab and the rdf / sparql / sparql-data hooks all call this. Older exports used
 * `urn:nf:<host>:<uuid>` (and briefly `urn:nf:site:<site>:<uuid>`); the sparql-data hook and the Python client still
 * read such point IRIs.
 * @returns {string}
 */
function rdfBaseOf() {
  return "urn:nf:";
}

/**
 * Turtle for the model + the set of tags that aren't in the Haystack libs above.
 *
 * External time-series references (slice 6): every exported point links to where its history
 * lives using Brick's reference schema (ref:):
 *   <point> ref:hasExternalReference [ a ref:TimeseriesReference ;
 *       ref:hasTimeseriesId "<NF point uuid>" ; ref:storedAt local:store_nf ;
 *       rdfs:label "NF history" ; schema:url <{nfBase}/api/v1/point/data?uuids=<uuid>> ] .
 * local:store_nf is the NF store node. nfBase = opts.nfBase, else the page origin (never a
 * hard-coded host); with neither, the URL is omitted and the uuid is the only key. NF's class and
 * the FDD hook's ruleRef are exported as local:nfClass / local:ruleRef (defined as rdf:Property), and an
 * explicit `ofddRole` attr as local:ofddRole.
 * Full edition: pass opts.timescale = { label, uri } to add a second reference per point,
 * stored at local:store_timescaledb (same uuid; the TimescaleDB rows are keyed by it). Lite has no
 * TimescaleDB and never passes it.
 */
function modelToTurtle(model, base, opts = {}) {
  const nfBase = (opts.nfBase ?? (typeof location !== "undefined" && location.origin !== "null" ? location.origin : "")).replace(/\/$/, "");
  const tsdb = opts.timescale || null;
  const nonStandard = new Set();
  const usedProps = new Set();
  const tag = (t) => {
    if (TAG_NS[t]) return `${TAG_NS[t]}:${t}`;
    nonStandard.add(t);
    return `local:${ttlId(t)}`;
  };
  const lines = [
    ...Object.entries(HS_NS).map(([p, u]) => `@prefix ${p}: <${u}> .`),
    "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
    `@prefix local: <${base}> .`, "",
  ];
  // Subjects (5.0.3): a Haystack id is only unique within a site (two sites can both have "AHU-1"), so site, equip and
  // device subjects are the record's NF uuid when it has one (like the points), else a site-prefixed id
  // (`<siteRef>/<id>`, sanitized; a site is just its id). Refs resolve to the referenced record's subject through the
  // model (equipRef / deviceRef inside the referrer's own site); a ref whose target is unknown or ambiguous keeps the
  // old `local:<id>` form, so the checker flags it as dangling.
  const siteOfRec = (r) => (r.attrs || {}).siteRef || "";
  const subjectOf = (r, isSite) => (r.uuid ? ttlId(r.uuid) : ttlId(isSite ? idOf(r) : `${siteOfRec(r)}/${idOf(r)}`));
  const subjects = { site: new Map(), equip: new Map(), device: new Map() };   // kind -> id -> [{ site, subject }]
  const named = { site: new Map(), equip: new Map(), device: new Map() };      // kind -> display name -> [{ site, subject }]
  const register = (kind, r) => {
    const id = idOf(r), list = subjects[kind].get(id) || [];
    const x = { site: kind === "site" ? id : siteOfRec(r), subject: subjectOf(r, kind === "site") };
    list.push(x);
    subjects[kind].set(id, list);
    // the same aliases the run-proof resolver accepts (runProofNames): the record name and its dis
    for (const alias of new Set([r.name, (r.attrs || {}).dis].filter((v) => v && v !== id))) {
      named[kind].set(alias, [...(named[kind].get(alias) || []), x]);
    }
  };
  for (const s of model.sites) register("site", s);
  for (const e of model.equips) register("equip", e);
  for (const d of model.devices) register("device", d);
  /** Subject a ref points at, or null (unknown / ambiguous). `site` = the referrer's siteRef. */
  const resolve = (kind, id, site) => {
    // "feeder" refs (airRef / chilledWaterRef / hotWaterRef / isFedBy / feeds) match ids and display-name aliases
    // together, as runProofFeeders does: a ref matching two records at the site (one by id, one by name) binds nothing.
    // Every other ref (siteRef, equipRef) is an id: the alias is only a fallback when no record has that id.
    const feeder = kind === "feeder";
    if (feeder) kind = "equip";
    const all = feeder ? [...(subjects[kind].get(id) || []), ...(named[kind].get(id) || [])]
      : (subjects[kind].get(id) || named[kind].get(id) || []);
    const list = [...new Map(all.map((x) => [x.subject, x])).values()];
    const scoped = kind === "site" ? list : list.filter((x) => x.site === site);
    const pick = scoped.length ? scoped : !site ? list : list.filter((x) => !x.site);   // an entity without a siteRef is shared
    return pick.length === 1 ? pick[0].subject : null;
  };
  const entity = (subject, type, label, tags, refs, extra = []) => {
    const body = [`a ${type}`, `rdfs:label ${ttlStr(label)}`];
    if (tags.length) body.push(`ph:hasTag ${tags.map(tag).join(", ")}`);
    for (const [prop, target] of refs) if (target) body.push(`${prop} local:${ttlId(target)}`);
    body.push(...extra);
    lines.push(`local:${ttlId(subject)}\n    ${body.join(" ;\n    ")} .`, "");
  };
  // refs of a record in `site`: [prop, kind, id] -> [prop, subject-or-raw-id]
  const refsOf = (site, list) => list.map(([prop, kind, id]) => [prop, id && (kind ? resolve(kind, id, site) || id : id)]);
  for (const s of model.sites) {
    entity(subjectOf(s, true), "phIoT:site", s.name, ["site"], []);
  }
  for (const e of model.equips) {
    const a = e.attrs || {};
    // Run-proof links (#1608): the refs and feeds the run-proof resolution follows (sql/fdd/run_proof.json)
    const links = (v) => (Array.isArray(v) ? v : String(v || "").split(",")).map((x) => String(x).trim().replace(/^@/, "")).filter(Boolean);
    entity(subjectOf(e), "phIoT:equip", e.name, markersOf(e), refsOf(a.siteRef, [
      ["phIoT:siteRef", "site", a.siteRef],
      ...["airRef", "chilledWaterRef", "hotWaterRef"].filter((r) => a[r]).map((r) => [`phIoT:${r}`, "feeder", String(a[r]).trim().replace(/^@/, "")]),
      ...links(a.isFedBy).map((id) => ["brick:isFedBy", "feeder", id]),
      ...links(a.feeds).map((id) => ["brick:feeds", "feeder", id]),
    ]));
  }
  for (const d of model.devices) {
    const a = d.attrs || {};
    entity(subjectOf(d), "phIct:device", a.dis || d.name, markersOf(d),
      refsOf(a.siteRef, [["phIoT:siteRef", "site", a.siteRef], ["phIoT:equipRef", "equip", a.equipRef]]));
  }
  const stations = [...new Set(model.points.map((p) => p.weatherStationRef).filter(Boolean))];
  for (const ws of stations) entity(ws, "phIoT:weatherStation", ws, ["weatherStation"], []);
  for (const p of model.points.filter((x) => x.tags.length || ((x.rec || {}).attrs || {}).ofddRole)) {
    const extra = [];
    if (p.units) extra.push(`ph:unit ${ttlStr(p.units)}`);
    if (p.kind) extra.push(`ph:kind ${ttlStr(p.kind)}`);
    // Typed link to the point's history (schema:url, not an untyped rdfs:seeAlso).
    const link = nfBase ? ` ;
            schema:url <${nfBase}/api/v1/point/data?uuids=${encodeURIComponent(p.uuid)}>` : "";
    const tsRef = (store, extraLink = "") =>
      `ref:hasExternalReference [ a ref:TimeseriesReference ;
            rdfs:label "${store === "store_nf" ? "NF history" : "TimescaleDB history"}" ;
            ref:hasTimeseriesId ${ttlStr(p.uuid)} ;
            ref:storedAt local:${store}${extraLink} ]`;
    if (p.cls) { extra.push(`local:nfClass ${ttlStr(p.cls)}`); usedProps.add("nfClass"); }
    const ruleRef = ((p.rec || {}).attrs || {}).ruleRef;
    if (ruleRef) { extra.push(`local:ruleRef ${ttlStr(ruleRef)}`); usedProps.add("ruleRef"); }
    // An explicit Open-FDD role on the point (NF attr `ofddRole`, optional): lets a SPARQL query bind rule inputs
    // without guessing from classes / markers. The app's own binder still uses NF classes, then markers.
    const ofddRole = ((p.rec || {}).attrs || {}).ofddRole;
    if (ofddRole) { extra.push(`local:ofddRole ${ttlStr(ofddRole)}`); usedProps.add("ofddRole"); }
    extra.push(tsRef("store_nf", link));
    if (tsdb) extra.push(tsRef("store_timescaledb"));
    entity(p.uuid, "phIoT:point", p.dis, p.tags, refsOf(p.siteRef, [
      ["phIoT:siteRef", "site", p.siteRef], ["phIoT:equipRef", "equip", p.equipRef],
      ["phIct:deviceRef", "device", p.deviceRef], ["phIoT:weatherStationRef", null, p.weatherStationRef],
    ]), extra);
  }
  // Define the time-series stores the point references point at.
  if (model.points.some((x) => x.tags.length || ((x.rec || {}).attrs || {}).ofddRole)) {
    entity("store_nf", "ref:Database", "Normal Framework point history", [], [], [
      `schema:description "Time series read with GET /api/v1/point/data?uuids=<ref:hasTimeseriesId>"`,
      ...(nfBase ? [`schema:url <${nfBase}>`] : [])]);
    if (tsdb) {
      entity("store_timescaledb", "ref:Database", tsdb.label || "TimescaleDB", [], [],
        [`rdfs:comment ${ttlStr(tsdb.uri || "full profile: NF TimescaleDB northbound, keyed by ref:hasTimeseriesId")}`]);
    }
  }
  // Define the local properties we used (NF class, FDD rule of a result point).
  const PROPS = { nfClass: "NF ontology class of the point", ruleRef: "Open-FDD rule this result point belongs to",
    ofddRole: "Open-FDD rule input role of the point (explicit binding)" };
  for (const p of [...usedProps].sort()) entity(p, "rdf:Property", p, [], [], [`rdfs:comment ${ttlStr(PROPS[p])}`]);
  // Define every non-standard tag we used, so no term in the graph is left undefined.
  for (const t of [...nonStandard].sort()) {
    entity(t, "ph:marker", t, [], [], [`rdfs:comment "site-specific tag (not in the Haystack libs)"`]);
  }
  return { turtle: lines.join("\n"), nonStandard: [...nonStandard].sort() };
}
