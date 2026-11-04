/** vibe19 `RCX_FAMILY_ORDER` plus empty Heat pump / Weather placeholders. */
export const RCX_FAMILY_ORDER = [
  "Zones / VAV",
  "AHU / air",
  "Boiler / HW",
  "Chiller / CHW / tower",
  "Heat pump",
  "Metering",
  "Weather",
] as const;

/** vibe19 `REQUIRED_RCX_PRESET_IDS` — frozen catalog; do not drop ids. */
export const REQUIRED_RCX_PRESET_IDS = [
  "zone_comfort_rank",
  "zone_temps",
  "ahu_dats",
  "ahu_mats",
  "ahu_rats",
  "ahu_dampers",
  "duct_static_box",
  "ahu_sat_reset_scatter",
  "hw_reset_scatter",
  "chw_reset_scatter",
  "cw_reset_scatter",
  "vav_flows",
  "fan_speeds",
  "meter_elec_cdd",
  "meter_gas_hdd",
  "duct_static_ts",
  "chw_temps_ts",
  "cw_temps_ts",
] as const;

export const RCX_FAMILY_MIN_COUNTS: Record<string, number> = {
  "Zones / VAV": 3,
  "AHU / air": 7,
  "Boiler / HW": 1,
  "Chiller / CHW / tower": 4,
  Metering: 2,
};

export function sortRcxFamilies(families: string[]): string[] {
  const extra = families
    .filter((f) => !(RCX_FAMILY_ORDER as readonly string[]).includes(f))
    .sort((a, b) => a.localeCompare(b));
  const ordered = RCX_FAMILY_ORDER.filter((f) => families.includes(f));
  return [...ordered, ...extra];
}

export function familyPickerOptions(presetFamilies: string[]): string[] {
  const have = new Set(presetFamilies);
  return RCX_FAMILY_ORDER.filter(
    (f) => have.has(f) || f === "Heat pump" || f === "Weather",
  );
}
