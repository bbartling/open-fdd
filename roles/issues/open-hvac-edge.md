> **PRIORITY: ASAP, owner directive.** Unify Open-FDD's three role vocabularies (input_contract.json, the #1808 manifest, the #1807 OpenAPI) on roles/openfdd-roles.json (strict ASHRAE 223P plus exact Haystack 4 mapping) before any other 5.0.22 rule work. Includes renaming \*_position inputs that are bound to command points, and fixing unit mismatches (0-1 vs %, L/s vs m3/s).

**Title:** Adopt Open-FDD `roles/openfdd-roles.json`: canonical role names, QUDT units, one Haystack binding

## Problem

All paths are under `examples/edge-microdot/`.

- `edge_microdot/role_terms.py` keeps its own `ACRONYM_TO_223P` and `HAYSTACK_TO_223P` maps.
  `_expand_haystack()` turns any unknown label into a role name, so it invents vocabulary.
- `edge_microdot/role_contract.py` copies 14 names and units from the bbartling/open-fdd#1807 draft, which is being replaced.
- `oa_damper_pct`, `clg_valve_pct` and `htg_valve_pct` (command points) are stored as `*_position`.
- History stores flow in m3/s, power in W and energy in J (`history_store.py`, `units_si.py`). Only the UI converts
  (`ui_api.py` `_WIRE_UNIT`). Open-FDD rules expect L/s, kW and kWh.

Open-FDD 5.0.22 ships `roles/openfdd-roles.json` (86 roles; see its `README.md`) in the rules bundle. The edge
consumes it and keeps no role table of its own.

## Renames

| Edge name today | Canonical role |
|---|---|
| `outside_air_temperature` | `outdoor_air_intake_temperature` |
| `outside_air_humidity` | `outdoor_air_intake_relative_humidity` |
| `supply_fan_run_status` | `supply_fan_operating_status` |
| `outside_air_damper_position` (from `oa_damper_pct`, a `cmd` point) | `outdoor_air_intake_damper_position_command` |
| `outside_air_damper_position` (from a damper `sensor` point) | `outdoor_air_intake_damper_position` |
| `cooling_valve_position` (from `clg_valve_pct`, a `cmd` point) | `cooling_valve_position_command` |
| `heating_valve_position` (from `htg_valve_pct`, a `cmd` point) | `heating_valve_position_command` |
| `chilled_water_supply_temperature` | `supply_chilled_water_temperature` |
| `hot_water_supply_temperature` | `supply_hot_water_temperature` |
| `duct_static_pressure` | `discharge_air_static_pressure` |
| `duct_static_pressure_setpoint` | `discharge_air_static_pressure_setpoint` |
| `run_status` | `operating_status` |
| `discharge_air_volumetric_flow` | `discharge_air_volume_flow_rate` |
| `zone_air_volumetric_flow` | `discharge_air_volume_flow_rate` |

Unchanged: `discharge_air_temperature`, `discharge_air_temperature_setpoint`, `mixed_air_temperature`,
`return_air_temperature`, `zone_air_temperature`, `zone_air_temperature_setpoint`, and `supply_fan_command` (now
boolean; a 0-100 VFD speed is `supply_fan_speed_command`). `cooling_valve_position` and `heating_valve_position` stay
as feedback (`sensor`) roles. The other Open-FDD rule inputs come from the roles file under their canonical names, so
the edge needs no extra table.

## Unit changes

The wire unit is the QUDT local name in `units[...]`. Storage uses the same unit, and `source_unit` keeps the original.

| Quantity | Stored today | Stored after | Conversion |
|---|---|---|---|
| Volume flow | `m3/s` | `L-PER-SEC` | x1000 (`cfm` x0.4719474432, `gal/min` x0.0630901964) |
| Power | `W` | `KiloW` | x0.001 (`kW` passes through) |
| Energy | `J` | `KiloW-HR` | ÷3,600,000 (`kWh` passes through, `Wh` x0.001) |
| Temperature | `degC`; `K` passes through | `DEG_C` | `K` -273.15, `°F` (x-32)×5/9 |
| Pressure | `Pa` | `PA` | unchanged factors |
| Ratio | `%` | `PERCENT` | a 0-1 source is multiplied by 100 |
| Humidity, CO2 | `%RH`, `ppm` | `PERCENT_RH`, `PPM` | none |

Use `ingest_conversions` from the roles file in both `units_si.py` and the SQL in `history_store.py`, so they cannot
drift apart. Units of non-role points (Hz, bytes) are unchanged.

## Haystack binding

Replace `HAYSTACK_TO_223P` and `_expand_haystack()` with the rules in `haystack.binding_rules`:

- Match the NF class first, then all `markers` plus `custom_markers`. A point that carries any `forbid` marker never
  binds.
- Every point has exactly one function marker.
- `equip_markers` are matched on the parent equipment.
- A strict superset wins. A remaining tie leaves the point unbound.

An unknown label never becomes a role: it gets no role, and the UI lists it as unbound. `ACRONYM_TO_223P` shrinks to
reading `legacy_keys` and `aliases` from the roles file, used only to migrate stored rows and old configs.

## Pinning

- Vendor `openfdd-roles.json` with the 5.0.22 rules bundle (`scripts/fetch_openfdd.py`, `edge_microdot/openfdd_pin.py`)
  and check its sha256 against the bundle manifest.
- Re-vendor `contract/open-fdd-ui-api.yaml` after Open-FDD regenerates it from the roles file.
- Never fetch either file at runtime.

## What can't be patched now

- **History already stored in m3/s, W and J, or under old role names.** Migrate it once in `history_store.py` (the
  existing `_legacy_tel` migration is the pattern): scale the values, set the unit, and rename the role through
  `legacy_keys`/`aliases`. Parquet files already exported keep their units; readers convert them by `source_unit`.
- **Until the 5.0.22 bundle is published,** vendor the roles file from an Open-FDD commit SHA, and record the SHA and
  sha256.
- **`bask_223p/`** (the TTL exporter) uses its own local types. Align it to the `s223` basis in the roles file in a
  follow-up.
- **`sql/fdd` vendored `core.sql`** changes in 5.0.22 (saved-tuning migration). Re-vendor it byte for byte with the
  bundle.

## Drift CI to add

1. Rewrite `tests/test_role_parity.py`:
   - the vendored roles file's sha256 equals the pin
   - every role the edge stores, streams or serves is a canonical `role`
   - each unit equals the role's `unit`
   - no `legacy_keys` or `aliases` value appears outside migration code
2. A matcher test: run the binding code on every role's own tag sets and check that each set binds exactly its role.
   Also check that a `max` airflow point never binds `discharge_air_volume_flow_rate_setpoint`, a `cmd` damper point
   never binds a `*_position` role, and an unknown label binds nothing.
3. A unit test: `units_si.to_si` and the `history_store.py` SQL produce the same value and unit as
   `ingest_conversions` for every entry.

## Acceptance criteria

- [ ] `role_contract.py`'s hand table is gone. Names, units and ranges come from the vendored roles file.
- [ ] `role_terms.py` has no hand map and no `_expand_haystack()`. Binding follows `haystack.binding_rules`.
- [ ] New history rows store L/s, kW and kWh, and existing rows are migrated exactly once (a test runs the migration
      twice).
- [ ] `ui_api.py` serves QUDT unit names and does no unit scaling.
- [ ] Every role served by the UI API is a canonical role and passes the vendored OpenAPI contract tests.
- [ ] The three drift tests above pass in CI.

## Checklist of files

- [ ] `edge_microdot/role_terms.py`, `edge_microdot/role_contract.py`
- [ ] `edge_microdot/units_si.py`, `edge_microdot/history_store.py`, `edge_microdot/ui_api.py`,
      `edge_microdot/static/sql.html`
- [ ] `edge_microdot/openfdd_pin.py`, `scripts/fetch_openfdd.py`, `OPENFDD_VERSION`
- [ ] `contract/open-fdd-ui-api.yaml`, `contract/mock/fixtures.mjs`, `scripts/serve_contract.py`
- [ ] `tests/test_role_parity.py`, `tests/test_bundle_and_reload.py`, `tests/test_nf_core_parity.py`
- [ ] `sql/fdd/` vendored `core.sql`
