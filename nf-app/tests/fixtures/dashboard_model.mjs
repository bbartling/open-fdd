// Synthetic one-site model for the Overview RCx dashboard and FDD tab checks (node tests and scripts/nf/ui_acceptance.mjs).
// Test-only, generic: `site-a`, AHU-1 / AHU-2 (one with DX cooling), CH-1 chiller, HW-1 boiler, VAV-1..3 zones, web weather.
// `dashboardModel({ plant })`: plant = "full" (every kind above) or "ahu" (air handlers only: no chiller, hot water, DX, zones).
// Records are NF point/query records (pointType SITE / EQUIPMENT / POINT, attrs with markers and refs).

const site = "site-a";
const rec = (uuid, name, pointType, attrs) => ({ uuid, name, pointType, attrs });
const equip = (id, markers, extra = {}) => rec(`eq-${id}`, id, "EQUIPMENT", { id, dis: id, siteRef: site, markers: `equip,${markers}`, ...extra });
const pt = (equipId, name, markers, extra = {}) => rec(`pt-${equipId}-${name}`, name, "POINT",
  { siteRef: site, equipRef: equipId, dis: `${equipId} ${name}`, markers: `point,his,cur,${markers}`, kind: "Number", unit: "°C", ...extra });
const bool = (equipId, name, markers, extra = {}) => pt(equipId, name, markers, { kind: "Bool", unit: "", ...extra });

/** @param {{ plant?: "full" | "ahu" }} [o] */
export function dashboardModel({ plant = "full" } = {}) {
  const full = plant === "full";
  const records = [rec("site-a-uuid", "Site A", "SITE", { id: site, dis: "Site A", markers: "site", tz: "America/Chicago" })];
  const points = [];
  for (const id of ["AHU-1", "AHU-2"]) {
    records.push(equip(id, "ahu"));
    points.push(
      bool(id, "supply_fan_operating_status", "discharge,fan,run,sensor", { class: "discharge-run-sensor" }),
      pt(id, "supply_fan_command", "discharge,fan,run,cmd", { class: "discharge-run-cmd", unit: "%" }),
      pt(id, "oat", "outside,air,temp,sensor", { class: "outside-air-temp-sensor" }),
      pt(id, "discharge_air_temperature", "discharge,air,temp,sensor", { class: "discharge-air-temp-sensor" }),
      pt(id, "return_air_temperature", "return,air,temp,sensor", { class: "return-air-temp-sensor" }),
      pt(id, "mixed_air_temperature", "mixed,air,temp,sensor", { class: "mixed-air-temp-sensor" }),
      pt(id, "oa-damper", "outside,damper,sensor", { class: "outside-damper-sensor", unit: "%" }),
    );
  }
  if (full) {
    points.push(bool("AHU-2", "dx-cool", "dx,cool,cmd"));                                   // AHU-2 is a DX unit
    records.push(equip("CH-1", "chiller"), equip("HW-1", "boiler"));
    points.push(bool("CH-1", "chiller_operating_status", "chiller,run,sensor"),
      pt("CH-1", "chw-supply", "chilled,water,leaving,temp,sensor"), pt("CH-1", "chw-return", "chilled,water,entering,temp,sensor"),
      pt("HW-1", "hw-supply", "hot,water,leaving,temp,sensor"), pt("HW-1", "hw-return", "hot,water,entering,temp,sensor"));
    for (const id of ["VAV-1", "VAV-2", "VAV-3"]) {
      records.push(equip(id, "vav", { airRef: id === "VAV-3" ? "AHU-2" : "AHU-1" }));
      points.push(pt(id, "zone-temp", "zone,air,temp,sensor", { class: "zone-air-temp-sensor" }),
        pt(id, "damper_position", "damper,cmd", { class: "damper-cmd", unit: "%" }),
        pt(id, "discharge-temp", "discharge,air,temp,sensor", { class: "discharge-air-temp-sensor" }));
    }
  }
  points.push(rec("pt-weather-oat", "web-oat", "POINT", { siteRef: site, weatherStationRef: "wx-1", dis: "Web outside air temp",
    markers: "point,his,weather,outside,air,temp,sensor", kind: "Number", unit: "°C" }));
  return { records, points };
}

const H = 3600e3;
/** A deterministic value for a point at ms `t` (SI): schedules on 06-18 local-ish, warm afternoons, a fan fault on AHU-1. */
export function dashboardValue(uuid, t) {
  const h = new Date(t).getUTCHours(), day = Math.floor(t / (24 * H));
  const occ = h >= 12 && h < 24;                       // 06:00-18:00 America/Chicago
  const oat = 14 + 10 * Math.sin(((h - 15) / 24) * 2 * Math.PI) + (day % 7) - 3;
  if (/web-oat|-oat$/.test(uuid)) return oat;
  if (/fan-status/.test(uuid)) return /AHU-1/.test(uuid) && day % 3 === 0 && h === 20 ? 0 : occ ? 1 : 0;   // a short AHU-1 trip
  if (/fan-cmd/.test(uuid)) return occ ? 85 : 0;
  if (/dx-cool|chiller-status/.test(uuid)) return occ && oat > 15 ? 1 : 0;
  if (/-discharge_air_temperature$/.test(uuid)) return occ ? 13 + (oat > 20 ? 0 : 2) : oat;
  if (/-return_air_temperature$/.test(uuid)) return 23;
  if (/-mixed_air_temperature$/.test(uuid)) return occ ? 0.3 * oat + 0.7 * 23 : 23;
  if (/oa-damper/.test(uuid)) return occ ? 30 : 0;
  if (/chw-supply/.test(uuid)) return 6.5 + Math.max(0, 22 - oat) * 0.15;
  if (/chw-return/.test(uuid)) return 12;
  if (/hw-supply/.test(uuid)) return 60 - Math.max(0, oat) * 0.8;
  if (/hw-return/.test(uuid)) return 45;
  if (/zone-temp/.test(uuid)) return 22 + (/VAV-3/.test(uuid) ? 2.5 : 0) + Math.sin(h / 3);
  if (/damper/.test(uuid)) return occ ? 45 : 10;
  if (/discharge-temp/.test(uuid)) return occ ? 18 : 22;
  return 0;
}

/** Hook-style FDD result points for one equipment (summary points the FDD tab reads): a fault, a pass, a skip, an insufficient. */
export function dashboardFddResults(nowIso) {
  const res = (equipId, ruleId, value, attrs) => ({ ...rec(`fdd-${equipId}-${ruleId}`, `${equipId} ${ruleId}`, "POINT", {
    siteRef: site, equipRef: equipId, ruleRef: ruleId, markers: "point,his,cur,fdd,fault", kind: "Number", unit: "h",
    fddOutput: "fault_hours", fddSummary: "equip", fddWindowHours: "24", fddLastRun: nowIso, ...attrs }),
    latestValue: value == null ? undefined : { ts: nowIso, double: value } });
  return [
    res("AHU-1", "CMD-1", 3.25, { fddStatus: "fault", fddCoverageHours: "24" }),
    res("AHU-1", "SCHED-247", 1.5, { fddStatus: "fault", fddCoverageHours: "24" }),
    res("AHU-1", "ECON-1", 0, { fddStatus: "ok", fddCoverageHours: "12" }),
    res("AHU-1", "FC1", null, { fddStatus: "not-assessed", fddReason: "no_run_proof: no status or command bound" }),
    res("AHU-1", "FC2", null, { fddStatus: "stale" }),
  ];
}