// Haystack model for the Open-FDD pages. Every tab renders from the object
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
async function loadModel() {
  const recs = await queryAll({ layer: "model" });
  const of = (t) => recs.filter((r) => r.pointType === t);
  const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: of("DEVICE"), points: [] };
  if (!model.sites.length) {
    throw new Error("no Haystack site in this NF's model layer; tag the site, equipment and points first");
  }
  model.points = await loadPoints(model);
  return model;
}

/** Points for every site in the model (cheap enough to re-run on the live loop). */
async function loadPoints(model) {
  const pages = await Promise.all(model.sites.map((s) =>
    queryAll({ layer: "default", structuredQuery: field("siteRef", idOf(s)) })));
  return pages.flat().filter((r) => !ENTITY_TYPES.includes(r.pointType)).map(toPoint);
}

// ---- RDF (Turtle) export ----------------------------------------------------------
// Haystack 4 splits its defs over ph / phScience / phIoT / phIct. Markers outside the
// lists below are written under the local namespace and reported as non-standard.
const HS_NS = {
  ph: "https://project-haystack.org/def/ph/",
  phScience: "https://project-haystack.org/def/phScience/",
  phIoT: "https://project-haystack.org/def/phIoT/",
  phIct: "https://project-haystack.org/def/phIct/",
  ref: "https://brickschema.org/schema/Brick/ref#",
  schema: "https://schema.org/",
};
const TAG_LIB = {
  phScience: ["air", "water", "temp", "humidity", "pressure", "dewPoint", "co2", "flow", "enthalpy", "concentration"],
  phIct: ["device", "controller", "network", "bacnet", "modbus"],
  phIoT: [
    "site", "space", "equip", "point", "sensor", "cmd", "sp", "his", "cur", "writable",
    "discharge", "outside", "zone", "return", "mixed", "exhaust", "inlet", "economizer",
    "damper", "fan", "run", "heat", "cool", "stage", "valve", "enable", "occ", "unocc",
    "ahu", "fcu", "vav", "weather", "weatherStation", "elec", "meter", "chilled", "hot",
  ],
};
const TAG_NS = Object.fromEntries(Object.entries(TAG_LIB).flatMap(([ns, tags]) => tags.map((t) => [t, ns])));

const ttlStr = (s) => `"${String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n")}"`;
const ttlId = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, "_");

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
 * the FDD hook's ruleRef are exported as local:nfClass / local:ruleRef (defined as rdf:Property).
 * Full profile hook: pass opts.timescale = { label, uri } to add a second reference per point,
 * stored at local:store_timescaledb (same uuid; the TimescaleDB rows are keyed by it).
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
  const entity = (subject, type, label, tags, refs, extra = []) => {
    const body = [`a ${type}`, `rdfs:label ${ttlStr(label)}`];
    if (tags.length) body.push(`ph:hasTag ${tags.map(tag).join(", ")}`);
    for (const [prop, target] of refs) if (target) body.push(`${prop} local:${ttlId(target)}`);
    body.push(...extra);
    lines.push(`local:${ttlId(subject)}\n    ${body.join(" ;\n    ")} .`, "");
  };
  for (const s of model.sites) {
    entity(idOf(s), "phIoT:site", s.name, ["site"], []);
  }
  for (const e of model.equips) {
    const a = e.attrs || {};
    entity(idOf(e), "phIoT:equip", e.name, markersOf(e), [["phIoT:siteRef", a.siteRef]]);
  }
  for (const d of model.devices) {
    const a = d.attrs || {};
    entity(idOf(d), "phIct:device", a.dis || d.name, markersOf(d),
      [["phIoT:siteRef", a.siteRef], ["phIoT:equipRef", a.equipRef]]);
  }
  const stations = [...new Set(model.points.map((p) => p.weatherStationRef).filter(Boolean))];
  for (const ws of stations) entity(ws, "phIoT:weatherStation", ws, ["weatherStation"], []);
  for (const p of model.points.filter((x) => x.tags.length)) {
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
    extra.push(tsRef("store_nf", link));
    if (tsdb) extra.push(tsRef("store_timescaledb"));
    entity(p.uuid, "phIoT:point", p.dis, p.tags, [
      ["phIoT:siteRef", p.siteRef], ["phIoT:equipRef", p.equipRef],
      ["phIct:deviceRef", p.deviceRef], ["phIoT:weatherStationRef", p.weatherStationRef],
    ], extra);
  }
  // Define the time-series stores the point references point at.
  if (model.points.some((x) => x.tags.length)) {
    entity("store_nf", "ref:Database", "Normal Framework point history", [], [], [
      `schema:description "Time series read with GET /api/v1/point/data?uuids=<ref:hasTimeseriesId>"`,
      ...(nfBase ? [`schema:url <${nfBase}>`] : [])]);
    if (tsdb) {
      entity("store_timescaledb", "ref:Database", tsdb.label || "TimescaleDB", [], [],
        [`rdfs:comment ${ttlStr(tsdb.uri || "full profile: NF TimescaleDB northbound, keyed by ref:hasTimeseriesId")}`]);
    }
  }
  // Define the local properties we used (NF class, FDD rule of a result point).
  const PROPS = { nfClass: "NF ontology class of the point", ruleRef: "Open-FDD rule this result point belongs to" };
  for (const p of [...usedProps].sort()) entity(p, "rdf:Property", p, [], [], [`rdfs:comment ${ttlStr(PROPS[p])}`]);
  // Define every non-standard tag we used, so no term in the graph is left undefined.
  for (const t of [...nonStandard].sort()) {
    entity(t, "ph:marker", t, [], [], [`rdfs:comment "site-specific tag (not in the Haystack libs)"`]);
  }
  return { turtle: lines.join("\n"), nonStandard: [...nonStandard].sort() };
}
