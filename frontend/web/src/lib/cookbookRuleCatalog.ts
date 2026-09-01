import type { FddRuleSummary } from "../api/fddApi";
import {
  mergeRuleDescriptionsFromApi,
  ruleDescription,
  ruleLabelStandard,
} from "./ruleLabels";

/** Haystack tag hints for health-matrix tooltips (not display names). */
const HAYSTACK_TAGS: Record<string, string[]> = {
  "AHU-SATDEV": ["dischargeAir", "dischargeAirSp"],
  "AHU-DUCTHI": ["ductStatic", "ductStaticSp", "fan"],
  "ECON-1": ["outsideAir", "outsideAirDamper", "fan"],
  "ECON-2": ["outsideAir", "outsideAirDamper", "fan"],
  "CHW-1": ["chilledWaterSupply", "chilledWaterReturn"],
  "CHW-2": ["chilledWaterDiffPressure", "chilledWaterDiffPressureSp"],
  "CHW-3": ["condenserWaterSupply", "condenserWaterReturn"],
  "HP-1": ["dischargeAir", "zoneAir", "fan"],
  FC5: ["hotWaterSupply"],
  FC6: ["hotWaterSupply"],
  FC8: ["hotWaterSupply"],
  "VAV-3": ["outsideAir", "reheatValve", "zoneAirflow"],
  "VAV-4": ["damper", "zoneAirflow"],
  "VAV-5": ["reheatValve", "coolingValve"],
  "VAV-7": ["zoneAirflow", "damper"],
  "OAT-METEO": ["outsideAir", "web-outside-air-temp"],
  "WX-1": ["outsideAir"],
  FC1: ["ductStatic", "ductStaticSp"],
};

export function ruleCatalogEntry(ruleId: string): {
  description: string;
  haystackTags: string[];
} {
  return {
    description: ruleDescription(ruleId),
    haystackTags: HAYSTACK_TAGS[ruleId] ?? [],
  };
}

/** @deprecated use mergeRuleDescriptionsFromApi */
export function mergeRuleCatalogFromApi(rules: FddRuleSummary[]): void {
  mergeRuleDescriptionsFromApi(rules);
}

/** Matrix column header: rule id + cookbook description + Haystack tags. */
export function healthColumnHeader(
  ruleId: string,
  haystackFallback?: string[],
): string {
  const { haystackTags } = ruleCatalogEntry(ruleId);
  const tags = haystackTags.length ? haystackTags : (haystackFallback ?? []);
  const tagPart = tags.length ? ` · ${tags.join(", ")}` : "";
  return `${ruleLabelStandard(ruleId)}${tagPart}`;
}
