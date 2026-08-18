# Package authoring (any BAS job)

Open-FDD consumes a generic `openfdd_package_v1` zip. Analytics, FDD, RCx, motors, mixing, and BAS-vs-web OAT read **mapped SQL roles** after ingest — they do **not** know Metasys, ALC, Niagara, or a campus name.

If Overview tables, RCx plots, Inspect traces, or health matrices are empty, the **package map is incomplete**. That is not an engine bug. Map or synthesize columns **in the zip**, then `POST /api/csv/import/package`.

**Never** hard-code a site, vendor suffix table, city, or equipment id in product code (`services/`, `sql_rules/`, `frontend/web`, `mcp/`). Gold ids: `AHU_1`, `VAV_1`, `CHW_1`, `weather/`.

Haystack names in sidecar `points` translate via `haystack_point_to_role` (`discharge-air-temp` → `sat`). Do not invent a second vocabulary. Alias table: [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../migration/vibe19/ROLE_MAPPING_PARITY.md). Ingest shapes: [`docs/RUST_DATAFUSION_ENGINE.md`](../RUST_DATAFUSION_ENGINE.md).

## What the preprocess agent must put in the zip

| Need | Haystack `points` / SQL roles | If the BAS has no binary point |
| --- | --- | --- |
| Motors (fan / pump / tower) | `fan-status` → `fan_status`; `chw-pump-status` → `chw_pump_status`; `hw-pump-status` → `hw_pump_status` | Map VFD % as `fan-cmd` / pump cmd. **Synthesize** 0/1 status (speed ≥ ~5%) in the wide CSV. Never invent hours from leave temp. Document the threshold in the **site preprocess repo**. |
| Compressor / mech-cooling OAT bins | `chiller-status` / `compressor-status` (cmd / amps / power also OK) | Synthesize status from % cooling output if needed. **Never** map CHW pump or AHU `cooling-valve` / `clg_valve_pct` as compressor proof. Map CHW temps to `chilled-water-supply-temp` / `chilled-water-return-temp`. Proof order: status → verified cmd → amps/power. |
| Mixing / economizer | `fan-status` (on) + `outside-air-temp` + `return-air-temp` + `mixed-air-temp` plus enough `\|OAT−RAT\|≥10°F` samples | Copy **site-global** BAS OA onto every AHU as `outside-air-temp`. Missing any role → skip, don’t crash. |
| VAV / zone | `zone-air-temp`, `zone-airflow`, `damper`, `reheat-valve` | `zone-airflow` = **actual CFM**, never the airflow setpoint. Stamp `equipType: vav`. |
| BAS vs web OAT | BAS `outside-air-temp` **and** `{building}/weather/history_wide.csv` → `web-outside-air-temp` (`web_oa_t`) | Fetch weather at **this job’s** lat/lon; interpolate onto the HVAC UTC grid. `prefer_web_oat: true`. Weather folder is **not** equipment. |
| Equipment typing | `equipType` + `equipment_type` | `rtu`→AHU; unit vent / FCU with fans → `ahu`; chiller plant → `chwPlant`; `heatPump`→`HP`. Id-substring fallback is last resort. |

Setpoints (`*-sp`, airflow SP) must never steal process-variable roles.

## D1–D9 (Open-FDD)

### D1. Analytics are role-driven

Empty Overview tables, RCx figures, Inspect overlays, or `?/3` health scores mean missing roles or missing FDD evidence — map in the zip, do not patch Rust.

### D2. Stamp types — do not rely on folder names

Canonical `equipType`: `ahu` `vav` `chwPlant` `boiler` `heatPump` `weather`. Folder `JRH-RM717-VMA-…` is **UNKNOWN** if unstamped. Product SQL helpers (`plant_group_for`, `chiller_like_equipment_sql`) still help CH-1, but agents must stamp types.

### D3. Web weather — package sidecar, not product config

- `{building}/weather/history_wide.csv` with `web-outside-air-temp` (°F).
- Align `timestamp_utc` to the HVAC grid.
- Lat/lon belongs in preprocess. No default city in product.
- B100 / OAT-METEO needs mapped `web_oa_t`.

### D4. Fan / pump / tower motor proof

Status/cmd before amps. Never invent motor hours from leave temperature.

### D5. Compressor proof ≠ valve ≠ pump

Mech-cooling OAT bins (`mechanical-cooling-oat-bins-v2`): compressor devices only. Never CHW pump status/cmd, fan status, cooling demand, or `clg_valve_pct`.

### D6. VAV / zone

Actual CFM + zone sensor + damper + reheat. Stamp `vav`.

### D7. Mixing scatter

Fan on + OA + RA + MA + enough `|OAT−RAT|`. Missing role → skip.

### D8. Zip hygiene

- `timestamp_utc` ISO-8601 UTC (`Z` or `+00:00`)
- UTF-8 wide CSV; one point per column
- Sibling Haystack JSON: `points` / `column_roles` keys = Haystack names; values = **exact CSV headers**. String `"equip": "AHU_1"` is a device id, not a nested package map.
- Forward-slash zip paths
- `weather/` nested under the building folder
- Seed: `POST /api/csv/import/package`. Hourly: `POST /api/csv/import/package/append` (`confirm:true`)

### D9. What product must never grow

No `if building == …`, no vendor suffix table, no default weather city, no glycol special case. Vendor dictionaries stay in preprocess zips.

## Example sibling map

```json
{
  "equipType": "ahu",
  "equip": "AHU_1",
  "points": {
    "discharge-air-temp": "SAT",
    "mixed-air-temp": "MAT",
    "return-air-temp": "RAT",
    "outside-air-temp": "OAT",
    "fan-status": "SF_S",
    "oa-damper": "MAD_C"
  }
}
```

`discharge-air-temp` → SQL `sat` via `haystack_point_to_role`.

## Agent import path (no new MCP write tools)

Use existing tools: `openfdd_csv_import_*`, `openfdd_csv_package_append`, `openfdd_ingest_contract`. SCAFFOLD `package_preflight` / `mapping_suggest` are **not** in the `mcp/` crate this cycle.

TADCO / Niagara long-format grids are a **preprocess example** (pivot before ingest), not product hardcoding.
