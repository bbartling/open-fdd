import type { FddRuleSummary } from "../api/fddApi";

/** Cookbook / registry descriptions — keep aligned with `sql_rules/registry.yaml`. */
const RULE_CATALOG: Record<
  string,
  { description: string; haystackTags?: string[] }
> = {
  "AHU-SATDEV": {
    description: "SAT deviation from setpoint",
    haystackTags: ["dischargeAir", "dischargeAirSp"],
  },
  "AHU-DUCTHI": {
    description: "Duct static pressure high",
    haystackTags: ["ductStatic", "ductStaticSp", "fan"],
  },
  "ECON-1": {
    description: "Economizer stuck closed when OAT favorable",
    haystackTags: ["outsideAir", "outsideAirDamper", "fan"],
  },
  "ECON-2": {
    description: "Economizer stuck open when OAT unfavorable",
    haystackTags: ["outsideAir", "outsideAirDamper", "fan"],
  },
  "CHW-1": {
    description: "Low chilled-water ΔT",
    haystackTags: ["chilledWaterSupply", "chilledWaterReturn"],
  },
  "CHW-2": {
    description: "DP below SP at max pump speed",
    haystackTags: ["chilledWaterDiffPressure", "chilledWaterDiffPressureSp"],
  },
  "CHW-3": {
    description: "Condenser water ΔT low",
    haystackTags: ["condenserWaterSupply", "condenserWaterReturn"],
  },
  "HP-1": {
    description: "Discharge cold when heating",
    haystackTags: ["dischargeAir", "zoneAir", "fan"],
  },
  "FC5": { description: "Boiler short cycling", haystackTags: ["hotWaterSupply"] },
  "FC6": { description: "Boiler lockout / failure", haystackTags: ["hotWaterSupply"] },
  "FC8": { description: "Boiler efficiency degradation", haystackTags: ["hotWaterSupply"] },
  "VAV-3": {
    description: "Excessive reheat during warm weather",
    haystackTags: ["outsideAir", "reheatValve", "zoneAirflow"],
  },
  "VAV-4": {
    description: "Damper hunting / oscillation",
    haystackTags: ["damper", "zoneAirflow"],
  },
  "VAV-5": {
    description: "Simultaneous heating and cooling",
    haystackTags: ["reheatValve", "coolingValve"],
  },
  "VAV-7": {
    description: "Low airflow at full cooling",
    haystackTags: ["zoneAirflow", "damper"],
  },
  "OAT-METEO": {
    description: "Equipment OAT vs weather-staged wx OAT",
    haystackTags: ["outsideAir", "web-outside-air-temp"],
  },
  "WX-1": {
    description: "OA temperature spike",
    haystackTags: ["outsideAir"],
  },
};

export function ruleCatalogEntry(ruleId: string): {
  description: string;
  haystackTags: string[];
} {
  const hit = RULE_CATALOG[ruleId];
  if (hit) {
    return {
      description: hit.description,
      haystackTags: hit.haystackTags ?? [],
    };
  }
  return { description: ruleId, haystackTags: [] };
}

export function mergeRuleCatalogFromApi(rules: FddRuleSummary[]): void {
  for (const r of rules) {
    const id = String(r.rule_id ?? "").trim();
    if (!id || RULE_CATALOG[id]) continue;
    RULE_CATALOG[id] = {
      description: String(r.description ?? id),
      haystackTags: (r.required_roles ?? []).slice(0, 4),
    };
  }
}

/** Matrix column header: rule id + cookbook description + Haystack tags. */
export function healthColumnHeader(
  ruleId: string,
  haystackFallback?: string[],
): string {
  const { description, haystackTags } = ruleCatalogEntry(ruleId);
  const tags = haystackTags.length ? haystackTags : (haystackFallback ?? []);
  const tagPart = tags.length ? ` · ${tags.join(", ")}` : "";
  return `${ruleId} — ${description}${tagPart}`;
}
