# Data-model driven vs hard-linked (App 19)

Prefer **Haystack point names** and package / column-map config over equipment-name heuristics.

## Typed equipment is canonical

Resolver: `app.site_model.resolve_equipment_type` / `stamp_equipment_type`.

| Priority | Source |
| --- | --- |
| 1 | `df.attrs["equipment_type"]` (stamped on load) |
| 2 | role_map / site / column_map `equipment_type` or `equipType` |
| 3 | `equipment_type_from_id` (id substring) — **fallback only** |

**Normalize:** `heatPump` / `HEAT_PUMP` → `HP`; `RTU` / rooftop → `AHU` (use DX points for mechanical cooling). Agents must stamp `equipType` in `column_map.json` so rules/analytics/RCx do not guess from folder names.

Cookbook kinds (`infer_equipment_kind`) and RCx membership use the resolved type — **no id-substring membership** in `collect_oat_scatter` / `collect_role_series`.

## Already data-model driven

| Concern | Mechanism |
| --- | --- |
| Point → rule inputs | Haystack JSON / `role_map` / `columns.csv` → `apply_role_map` |
| Equipment type | `resolve_equipment_type` (attrs → map → id) |
| Chiller weekly **motor** hours | Designated pump points `chw-pump-status` / `chw-pump-cmd` / optional `chw_pump_equipment` (motor/circulation only — **not** compressor proof) |
| Motor weekly series | Mapped `fan-*` / `chw-pump-*` / `hw-pump-*` / `pump-*` before named-pump regex |
| Package layout | `openfdd_package_v1` manifest + folder names as equipment ids |
| Rule applicability | `CookbookRule.equipment_kinds` via resolved type |
| Units display | `unit_system` + point unit map |
| Mech-cooling OAT bins | Compressor / chiller proof only — see below (**never** pump-alone) |
| RCx preset membership | Resolved `equipment_type` + point-based series |
| AHU↔VAV topology | `vav_to_ahu_simple.csv` → Data Model Topology section |

## Mechanical cooling proof points (OAT bins)

**Counts as mechanical compressor runtime** (`app/analytics.py`). CHW **pump status/command alone does not count**.

| Equipment | Acceptable proof (deterministic priority) |
| --- | --- |
| Chiller / CHW plant | `chiller-status` / `compressor-status` → verified `compressor-cmd` → unit-aware `chiller-amps` / `chiller-power` / `compressor-power` / `compressor-current` above validated thresholds |
| AHU with DX (incl. RTU-as-AHU) | `compressor-status`, stage roles, `dx-cool-cmd`, `dx-cooling` (cooling-mode is a gate when required, not standalone proof) |
| Heat pump / VRF | Compressor status only with proven cooling mode; VRF outdoor compressor status with cooling mode |

**Does not count for OAT bins:** `chw-pump-status` / `chw-pump-cmd` / fan status alone, cooling demand alone, `cooling-valve` / `clg_valve_pct` / CHW AHU valve %. Pump roles remain for **motor weekly / plant circulation** analytics only (see table above). Optional inferred CHW leave-temp is labeled `inferred` and never applied to chilled-water AHU valves.

## Topology

VAV **fedBy** parent AHU; AHU **feeds** VAV children. Source: package
`vav_to_ahu_simple.csv` (never invented). Parent AHU `discharge-air-temp` may be
copied onto each VAV as `ahu-discharge-air-temp` for cross-equip rules.
