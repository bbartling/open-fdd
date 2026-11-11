// Model fixture for the plot-spec golden tests: the two-site SI dataset (two_site.mjs) plus a small generic
// chilled-water plant, a few AHU points and the FDD hook's result points, so rules and presets that the AHU-only
// dataset cannot feed (SV-RANGE on a chilled-water flow, FC1, CHW-1, the valve presets) have something to bind.
// Model only: ids, markers, classes, units. No history. Test-only (ESM). Names are `site-a` / `site-b` / `CH-1`.
//
//   node nf-app/tests/fixtures/plot_spec_model.mjs --write    # regenerate tests/fixtures/plot_spec/model.json
//
// The committed JSON is what the Python and JS producers read; plot-spec.test.mjs fails when it drifts from this file.
import crypto from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { twoSite } from "./two_site.mjs";

const catalog = JSON.parse(readFileSync(new URL("../../static/fdd-catalog.json", import.meta.url), "utf8"));
export const MODEL_PATH = new URL("../../../tests/fixtures/plot_spec/model.json", import.meta.url);

const uuidOf = (name) => {
  const h = crypto.createHash("sha1").update(`plot-spec:${name}`).digest("hex");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-5${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`;
};
const GENERIC = new Set(["point", "his", "cur", "writable"]);

/** A model.js point from an NF record (same shape as toPoint(); `latest` left out). */
function toPoint(rec) {
  const a = rec.attrs, tags = a.markers.split(",").filter(Boolean);
  return {
    uuid: rec.uuid, tags, dis: a.dis, units: a.unit || "", kind: a.kind || "Number",
    name: tags.filter((x) => !GENERIC.has(x) && x !== "sensor").join(" ") || rec.name,
    equipRef: a.equipRef || "", weatherStationRef: a.weatherStationRef || "", siteRef: a.siteRef || "",
    deviceRef: "", objectId: "", bacnet: "", cls: a.class || "", rec,
  };
}

export function buildPlotSpecModel() {
  const base = JSON.parse(JSON.stringify({ sites: twoSite.model.sites, equips: twoSite.model.equips, points: twoSite.model.points }));
  for (const p of base.points) delete p.latest;
  const sites = base.sites, equips = base.equips, points = base.points;

  const rolePoint = (siteId, equipId, role, { unit, kind = "Number" }) => {
    const def = catalog.roles[role];
    return toPoint({
      uuid: uuidOf(`${siteId}/${equipId}/${role}`), name: `${siteId} ${equipId} ${role}`, layer: "default", pointType: "POINT",
      attrs: { dis: `${equipId} ${def.name}`, markers: ["point", "his", ...def.markers].join(","), class: def.classes[0] || "",
        equipRef: equipId, siteRef: siteId, unit, kind },
    });
  };
  const resultPoint = (siteId, equipId, ruleId, markers, extra = {}) => toPoint({
    uuid: uuidOf(`${siteId}/${equipId}/${ruleId}/${markers}/${extra.sensorRef || ""}`), name: `${siteId} ${equipId} ${ruleId} ${markers}`,
    layer: "default", pointType: "POINT",
    attrs: { dis: `${equipId} ${ruleId} ${markers}`, markers: ["point", "his", ...markers.split("+")].join(","), class: "",
      equipRef: equipId, siteRef: siteId, unit: "", kind: "Number", ruleRef: ruleId, ...extra },
  });
  const uuidFor = (siteId, equipId, role) => uuidOf(`${siteId}/${equipId}/${role}`);

  // site-a AHU-1: valve, duct static (declared in inH2O to exercise conversion) and its setpoint
  points.push(rolePoint("site-a", "AHU-1", "clg_valve_pct", { unit: "%" }));
  points.push(rolePoint("site-a", "AHU-1", "duct_static", { unit: "inH2O" }));
  points.push(rolePoint("site-a", "AHU-1", "duct_static_sp", { unit: "Pa" }));

  // site-a plant: one generic chiller (units mixed on purpose: degF, gpm, %, and one point with no unit)
  equips.push({ uuid: uuidOf("site-a/CH-1"), name: "CH-1", layer: "model", pointType: "EQUIPMENT",
    attrs: { id: "CH-1", dis: "CH-1", markers: "equip,chiller", siteRef: "site-a" } });
  points.push(rolePoint("site-a", "CH-1", "chw_supply_t", { unit: "°F" }));
  points.push(rolePoint("site-a", "CH-1", "chw_return_t", { unit: "°F" }));
  points.push(rolePoint("site-a", "CH-1", "chw_flow", { unit: "gpm" }));
  points.push(rolePoint("site-a", "CH-1", "chw_pump_cmd", { unit: "%" }));
  points.push(rolePoint("site-a", "CH-1", "chiller_status", { unit: "", kind: "Bool" }));
  points.push(rolePoint("site-a", "CH-1", "chiller_power", { unit: "" }));      // no unit: dropped as unit_unusable

  // a weather point of site-a (fills web_* roles of every equip of the site)
  const wx = catalog.roles.web_oa_t;
  points.push(toPoint({ uuid: uuidOf("site-a/weather/web_oa_t"), name: "site-a weather web_oa_t", layer: "default", pointType: "POINT",
    attrs: { dis: "Outside air temp (weather)", markers: ["point", "his", ...wx.markers].join(","), class: "", siteRef: "site-a",
      weatherStationRef: "station-1", unit: "°C", kind: "Number" } }));

  // the FDD hook's result points: a timeline for FC1; only the rolling fault_pct for CHW-1; per-sensor results and a
  // timeline for the chilled-water flow under SV-RANGE (the other SV-RANGE sensors have neither)
  points.push(resultPoint("site-a", "AHU-1", "FC1", "fdd+fault_timeline"));
  points.push(resultPoint("site-a", "CH-1", "CHW-1", "fdd+fault"));
  const flow = uuidFor("site-a", "CH-1", "chw_flow");
  points.push(resultPoint("site-a", "CH-1", "SV-RANGE", "fdd+fault", { sensorRef: flow, roleRef: "chw_flow", fddSummary: "sensor" }));
  points.push(resultPoint("site-a", "CH-1", "SV-RANGE", "fdd+fault_timeline", { sensorRef: flow }));

  return { sites, equips, points };
}

export const modelJson = () => JSON.stringify(buildPlotSpecModel(), null, 2) + "\n";

if (process.argv[1] === fileURLToPath(import.meta.url) && process.argv.includes("--write")) {
  writeFileSync(MODEL_PATH, modelJson());
  console.log("wrote", fileURLToPath(MODEL_PATH));
}
