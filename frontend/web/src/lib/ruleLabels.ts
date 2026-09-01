import type { FddRuleSummary } from "../api/fddApi";

/** Registry `description` cache — merged from GET /api/fdd/rules at runtime. */
const descriptions = new Map<string, string>();

/** Seed known rules before API load (health matrix tooltips). */
const SEED_DESCRIPTIONS: Record<string, string> = {
  "AHU-SATDEV": "SAT deviation from setpoint",
  "AHU-DUCTHI": "Duct static pressure high",
  "ECON-1": "Economizer stuck closed when OAT favorable",
  "ECON-2": "Economizer stuck open when OAT unfavorable",
  "CHW-1": "Low chilled-water ΔT",
  "CHW-2": "DP below SP at max pump speed",
  "CHW-3": "Condenser water ΔT low",
  "HP-1": "Discharge cold when heating",
  FC5: "Boiler short cycling",
  FC6: "Boiler lockout / failure",
  FC8: "Boiler efficiency degradation",
  "VAV-3": "Excessive reheat during warm weather",
  "VAV-4": "Damper hunting / oscillation",
  "VAV-5": "Simultaneous heating and cooling",
  "VAV-7": "Low airflow at full cooling",
  "OAT-METEO": "Equipment OAT vs weather-staged wx OAT",
  "WX-1": "OA temperature spike",
  FC1: "Duct static below SP at full fan",
};

for (const [id, description] of Object.entries(SEED_DESCRIPTIONS)) {
  descriptions.set(id, description);
}

export function mergeRuleDescriptionsFromApi(rules: FddRuleSummary[]): void {
  for (const r of rules) {
    const id = String(r.rule_id ?? "").trim();
    if (!id) continue;
    const desc = String(r.description ?? "").trim();
    if (desc) descriptions.set(id, desc);
  }
}

export function ruleDescription(ruleId: string, fallback?: string): string {
  const id = ruleId.trim();
  if (!id) return "";
  return descriptions.get(id) ?? fallback?.trim() ?? id;
}

/** Machine key only — matrix column headers, compact badges. */
export function ruleLabelShort(ruleId: string): string {
  return ruleId.trim();
}

/** Sidebar, dropdowns, run tables — `{rule_id} — {description}`. */
export function ruleLabelStandard(ruleId: string, description?: string): string {
  const id = ruleId.trim();
  const desc = ruleDescription(id, description);
  if (!id) return desc;
  if (desc === id) return id;
  return `${id} — ${desc}`;
}

/** Plot title — standard label + equipment. */
export function ruleLabelPlotTitle(
  ruleId: string,
  equipmentId: string,
  description?: string,
): string {
  const base = ruleLabelStandard(ruleId, description);
  const eq = equipmentId.trim();
  return eq ? `${base} · ${eq}` : base;
}
