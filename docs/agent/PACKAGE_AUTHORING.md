# Package authoring (any BAS job)

Open-FDD consumes a generic `openfdd_package_v1` zip. Analytics, FDD, RCx, motors, mixing, and BAS-vs-web OAT read **mapped SQL roles** after ingest — they do **not** know Metasys, ALC, Niagara, or a campus name.

If Overview tables, RCx plots, Inspect traces, or health matrices are empty, the **package map is incomplete**. That is not an engine bug. Map or synthesize columns **in the zip**, then `POST /api/csv/import/package`.

**Never** hard-code a site, vendor suffix table, city, or fixture equipment id in product code (`services/`, `sql_rules/`, `frontend/web`, `mcp/`, PyPI report / fault / oracle). Gold ids (`AHU_1`, `VAV_1`, `CHW_1`, `weather/`) are layout examples, not selectors. Select equipment by `equipType` / `equipment_type`, roles, and the registry. Do not prefer `RTU_01` or `VAV_1` over type, and do not match `equipment_id` with a substring, prefix, `LIKE`, `contains`, or `starts_with` (`RTU_01` must not hit `RTU_010`). An exact id is allowed only after the type filter. `building_id` is a caller, request, JWT, or env parameter. Ops and stress may name a lab site as an env default; their selectors stay type-first and exact-id-only. Law: [`openfdd-site-identity`](../../openfdd_agent_spec/skills/openfdd-site-identity/SKILL.md).

**UI export is not SoT:** Mapping → Export site data model (JSON) / Export TTL (Turtle) are **derived views** of the same package inventory. Agents and FDD still author and resolve roles via zip maps → `columns.csv` → DataFusion SQL. Do not replace package authoring with Brick/SPARQL or treat downloaded `.ttl` as the ingest contract. Detail: [`docs/modeling/data-model-ttl.md`](../modeling/data-model-ttl.md).

Haystack names in sidecar `points` translate via `haystack_point_to_role` (`discharge-air-temp` → `sat`). Do not invent a second vocabulary. Alias table: [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../migration/vibe19/ROLE_MAPPING_PARITY.md). Ingest shapes: [`docs/RUST_DATAFUSION_ENGINE.md`](../RUST_DATAFUSION_ENGINE.md).

Modeling docs for agents: [`docs/modeling/`](../modeling/) — especially
[package-schema](../modeling/package-schema.md) (compact vs SCAFFOLD evidence),
[heat-pump buildings](../modeling/heat-pump-buildings.md),
[Haystack RDF profile](../modeling/haystack-rdf-profile.md) (strict
`ofdd_haystack_projection_v1` vs native exports), and
[rule readiness](../modeling/rule-readiness.md). A parseable ZIP is not
commissioning-grade FDD.

## What the preprocess agent must put in the zip

| Need | Haystack `points` / SQL roles | If the BAS has no binary point |
| --- | --- | --- |
| Motors (fan / pump / tower) | `fan-status` → `fan_status`; `chw-pump-status` → `chw_pump_status`; `hw-pump-status` → `hw_pump_status` | Map VFD % as `fan-cmd` / pump cmd. **Synthesize** 0/1 status (speed ≥ ~5%) in the wide CSV. Never invent hours from leave temp. Document the threshold in the **site preprocess repo**. |
| Compressor / mech-cooling OAT bins | `chiller-status` / `compressor-status` (cmd / amps / power also OK) | Synthesize status from % cooling output if needed. **Never** map CHW pump or AHU `cooling-valve` / `clg_valve_pct` as compressor proof. Map CHW temps to `chilled-water-supply-temp` / `chilled-water-return-temp`. Proof order: status → verified cmd → amps/power. |
| Mixing / economizer | `fan-status` (on) + `outside-air-temp` + `return-air-temp` + `mixed-air-temp` plus enough `\|OAT−RAT\|≥10°F` samples | Copy **site-global** BAS OA onto every AHU as `outside-air-temp`. Missing any role → skip, don’t crash. |
| VAV / zone | `zone-air-temp`, `zone-airflow`, `damper`, `reheat-valve` | `zone-airflow` = **actual CFM**, never the airflow setpoint. Stamp `equipType: vav`. |
| BAS vs web OAT | BAS `outside-air-temp` **and** `{building}/weather/history_wide.csv` → `web-outside-air-temp` (`web_oa_t`) | Fetch weather at **this job’s** lat/lon; interpolate onto the HVAC UTC grid. `prefer_web_oat: true`. Weather folder is **not** equipment. |
| Equipment typing | `equipType` (preferred; `equipment_type` accepted) | `rtu`→AHU; unit vent → `ahu`; FCU / standalone DDC → `zone_other`; chiller plant → `chwPlant`; `heatPump`→`HP`; electricity meter → `meter`. Stamp the type. A missing or unrecognized stamp stays unclassified. Do not infer kind from the equipment id, and do not add an id-substring selector. |
| Electricity meter (UTIL / SV / RCx metering) | Stamp `equipType: meter`; map `elec_power` / `electric_kw` / `kwh` (do not invent points) | BAS BACnet meter columns already named cookbook roles ingest as identity. Package `utilities_v1` monthly bills feed Metering UI. |

Setpoints (`*-sp`, airflow SP) must never steal process-variable roles.

## D1–D9 (Open-FDD)

### D1. Analytics are role-driven

Empty Overview tables, RCx figures, Inspect overlays, or `?/3` health scores mean missing roles or missing FDD evidence — map in the zip, do not patch Rust.

### D2. Stamp types — do not rely on folder names

Canonical `equipType`: `ahu` `vav` `chwPlant` `boiler` `heatPump` `weather` `meter`. Folder `JRH-RM717-VMA-…` is unclassified when the stamp is absent or unrecognized, and it matches nothing. Overview families, motor groups, VAV health, weather selection, plot cohorts, and rule applicability follow that stamp, then exact equipment ids. Never prefer a fixture id over the stamp. Never substring, prefix, `LIKE`, `contains`, or `starts_with` on the equipment id (`RTU_01` must not select `RTU_010`). A VAV parent is `parentAhu` / `parent_ahu` on the equipment map, an exact sibling id. The letters in the equipment id are not a parent. Do not hard-code a building id. Do not invent an MQTT delta payload ([#1043](https://github.com/bbartling/open-fdd/issues/1043), [#1045](https://github.com/bbartling/open-fdd/issues/1045), [#1046](https://github.com/bbartling/open-fdd/issues/1046), [#1047](https://github.com/bbartling/open-fdd/issues/1047), agent rule 64). Id text is not an authorized fallback.

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

No `if building == …`, no vendor suffix table, no default weather city, no glycol special case, no equipment-id `LIKE` / prefix / name filter, no MQTT delta payload. Vendor dictionaries stay in preprocess zips.

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

Vendor long-format BAS grids are a **preprocess example** (pivot before ingest), not product hardcoding.

## Equipment type precedence

Stamp each equipment block with `equipType` (preferred) or `equipment_type`. Open-FDD persists that stamp during package ingest and uses it as the classifier for inventory and analytics. The persisted building-scoped type metadata is part of the ingest contract, not a transient mapping hint. A folder named `AC_1` with `equipType: ahu` is an AHU. If the stamp is absent or unrecognized, the equipment stays unclassified. Id text cannot add or remove equipment that already has a stamp. Vendor/site-specific aliases belong in the preprocess package generator, never in product Rust.
