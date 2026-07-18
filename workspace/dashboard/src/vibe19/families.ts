/** Mechanical families for rule-tuning grouping — mirrors vibe19
 * `app/column_map_json.py` FAMILY_LABELS and the cookbook catalog family field. */

export const FAMILY_ORDER = [
  "sensor",
  "control",
  "ahu",
  "vav",
  "plant",
  "heatpump",
  "weather",
  "trim",
  "schedule",
  "other",
] as const;

export type RuleFamily = (typeof FAMILY_ORDER)[number];

export const FAMILY_LABELS: Record<RuleFamily, string> = {
  sensor: "1 · Sensor validation",
  control: "2 · Control loops",
  ahu: "3 · AHU / air handling",
  vav: "4 · VAV / terminal",
  plant: "5 · Central plant",
  heatpump: "6 · Heat pump",
  weather: "7 · Weather / OAT",
  trim: "8 · Trim & respond",
  schedule: "9 · Schedule / runtime",
  other: "10 · Other",
};

/** Explicit rule_id → family from the vibe19 cookbook catalog (source of truth). */
const RULE_FAMILY: Record<string, RuleFamily> = {
  "SV-RANGE": "sensor",
  "SV-FLATLINE": "sensor",
  "SV-SPIKE": "sensor",
  "SV-STALE": "sensor",
  "SV-RATE": "sensor",
  "SV-SLEW": "sensor",
  "PID-HUNT-1": "control",
  "AHU-SATDEV": "ahu",
  "AHU-DUCTHI": "ahu",
  "AHU-SIMUL": "ahu",
  "OAT-METEO": "ahu",
  "MECH-OAT-1": "ahu",
  "CMD-1": "ahu",
  "OA-1": "ahu",
  "DMP-1": "ahu",
  "VLV-1": "ahu",
  "CHW-NOLOAD-1": "plant",
  "CW-OPT-1": "plant",
  "CW-APR-1": "plant",
  "CW-FAN-1": "plant",
  "VAV-REHEAT": "vav",
  "VAV-AHU-LEAVE": "vav",
  "HP-1": "heatpump",
  "WX-1": "weather",
  "SCHED-247": "schedule",
};

/** Family for a rule id: explicit catalog map first, then prefix inference. */
export function ruleFamily(ruleId: string): RuleFamily {
  const id = ruleId.trim().toUpperCase();
  const explicit = RULE_FAMILY[id];
  if (explicit) return explicit;
  const prefix = id.split("-")[0] ?? "";
  if (prefix === "SV") return "sensor";
  if (prefix === "PID") return "control";
  if (/^FC\d+/.test(id) || prefix === "ECON" || prefix === "AHU" || prefix === "OAT") return "ahu";
  if (prefix === "VAV") return "vav";
  if (prefix === "CHW" || prefix === "CW" || prefix === "HW") return "plant";
  if (prefix === "HP") return "heatpump";
  if (prefix === "WX") return "weather";
  if (prefix === "TRIM") return "trim";
  if (prefix === "SCHED") return "schedule";
  return "other";
}

/** Group rule ids into ordered [family label, rule ids] buckets (empty families dropped). */
export function groupRulesByFamily(ruleIds: string[]): [string, string[]][] {
  const buckets = new Map<RuleFamily, string[]>();
  for (const id of ruleIds) {
    const fam = ruleFamily(id);
    const arr = buckets.get(fam) ?? [];
    arr.push(id);
    buckets.set(fam, arr);
  }
  return FAMILY_ORDER.filter((f) => buckets.has(f)).map((f) => [
    FAMILY_LABELS[f],
    buckets.get(f)!,
  ]);
}
