---
name: openfdd-rcx-fdd-plot-poll
description: >-
  From blank RCx or FDD plots, deduce missing historian roles and fieldbus poll
  catalog gaps. Triggers on empty RCx preset, empty FDD series, missing poll
  points, ACME field_devices gaps, TEC strip, Modbus boiler gateway strip.
---

# RCx / FDD plot → poll checklist

Blank plots are almost never a Plotly bug. They mean **missing SQL roles** in
historian (CSV map or MQTT publish) or **missing poll points** on fieldbus.
This skill turns an empty chart into a scrape-proven poll / map checklist.

## When to use

- RCx preset returns `points=0` / empty envelope / “unavailable (unmapped …)”
- FDD Plots series soft-empty after a successful rule run
- ACME / OT catalog edits for health-only @300 s poll
- Diffing Data Model gaps vs `REQUIRED_RCX_PRESET_IDS` + cookbook roles

## Sources of truth (read in this order)

1. [`frontend/web/src/nav/rcxCatalog.ts`](../../../frontend/web/src/nav/rcxCatalog.ts) — `REQUIRED_RCX_PRESET_IDS`
2. [`services/central/src/analytics/rcx_presets.rs`](../../../services/central/src/analytics/rcx_presets.rs) — preset → `role_col` / overlays
3. [`docs/agent/PACKAGE_AUTHORING.md`](../../../docs/agent/PACKAGE_AUTHORING.md) — Haystack → SQL roles by family
4. [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../../../docs/migration/vibe19/ROLE_MAPPING_PARITY.md) — alias table
5. `sql_rules/registry.yaml` — FDD `required_roles` ∪ `optional_roles` per rule
6. Live site Data Model / inventory (`GET` mapping) — mapped vs unmapped columns
7. Fieldbus poll catalog (`field_devices` / site private catalog) — what is actually polled

Companion: [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md) for zip maps;
[`openfdd-bacnet-ot-debug`](../openfdd-bacnet-ot-debug/SKILL.md) for Who-Is / ReadProperty.

## Workflow

### 1. Name the blank surface

| Surface | What empty means |
|---------|------------------|
| RCx preset | Missing `role_col` (and overlay) on matching `eq_kinds` |
| FDD series | Missing required∪optional roles on that equipment |
| Health matrix `?/3` | Missing proof roles **or** no FDD results yet |
| Inspect | Column present in Parquet but not selected / unmapped |

Do **not** patch central SQL to paper over a missing BACnet point.

### 2. Expand roles → Haystack → poll intent

For each blank preset / rule:

1. List cookbook SQL roles needed (process vars first; setpoints are additive).
2. Map each role to Haystack names via ROLE_MAPPING_PARITY / PACKAGE_AUTHORING.
3. Emit a **site poll matrix** row: `role | equip family | haystack | BACnet object (only if scrape-proven) | present in field_devices? | present in Data Model?`.

Never invent ZN-T / CFM / setpoints. If Mint scrape does not show the object, mark **GAP — scrape first**, do not add to poll.

### 3. Diff vs live catalog

- Inventory / Data Model: blank role = unmapped; column may still exist.
- `field_devices`: health-only poll @ **300 s** (compiled fieldbus floor).
- Prefer status/cmd before amps; never use valve % as compressor proof.

### 4. Drive catalog edits (strip list is mandatory)

**Include (examples — only when scrape-proven):**

| Family | Roles that light RCx / FDD |
|--------|----------------------------|
| VAV | `zone_t`, `zone_flow` (actual CFM), `damper_pct`, reheat valve, leave/DAT, airflow SP (SP as setpoint role only) |
| RTU / AHU | fan VFD %, duct static + SP, DAT/SAT, cool/compressor status+cmd, OA damper, BAS `oa_t` |
| Boiler / HW | HW supply/return, pump ΔP + SP, pump speed(s) — whitelist controller only |
| Weather | site BAS `oa_t` + `{building}/weather/` `web_oa_t` |

**Exclude / strip from poll catalogs:**

- **All TEC** BACnet zone controllers — do not poll; do not map as VAVs
- **Modbus↔BACnet boiler / integrator gateway** object trees — do not flood poll; use the real boiler controller whitelist only
- eGauge / full object dumps / invented points

### 5. Checklist template (copy into PR / BUG_REPORT)

```text
Site: <building_id>
Blank: RCx <preset_id> | FDD <rule_id>
Roles needed: …
Haystack: …
Scrape-proven BACnet: … | GAP
field_devices today: present / missing
Data Model: mapped / unmapped / absent column
Action: add poll | add map only | strip TEC/gateway | wait for scrape
Excluded: TEC=stripped gateway=stripped
```

## Quick RCx role cheat sheet (`REQUIRED_RCX_PRESET_IDS`)

| Preset | Primary role(s) |
|--------|-----------------|
| `zone_comfort_rank` / `zone_temps` / `vav_health_matrix` | `zone_t` (+ damper for rogue box) |
| `vav_flows` | `zone_flow` |
| `ahu_dats` / `ahu_sat_reset_scatter` | `sat` (+ web OAT for scatter) |
| `ahu_mats` / `ahu_rats` / `ahu_dampers` | `mat` / `rat` / `oa_damper_pct` |
| `fan_speeds` | fan speed / cmd |
| `duct_static_*` | duct static |
| `hw_reset_scatter` | HW temp + web OAT |
| `chw_*` / `cw_*` | CHW/CW temps + web OAT |
| `meter_*` | utility / meter roles |
| `bas_vs_web_oat` (additive) | `oa_t` + `web_oa_t` |

## Anti-patterns

- Adding TEC or Modbus gateway devices “so something shows up”
- Inventing points not on the Mint / site scrape
- Patching RCx SQL filters instead of stamping `equipType: vav` / mapping roles
- Treating empty Plotly as a frontend-only bug when envelope `rows`/`points` are empty
- Duplicating this skill into `~/.cursor/skills/`

## Done when

- Poll matrix lists every blank preset/rule role with scrape evidence or explicit GAP
- `field_devices` has health roles only; TEC + Modbus boiler gateway removed
- Data Model shows the new columns; RCx/FDD envelopes non-empty after next ingest cycle
