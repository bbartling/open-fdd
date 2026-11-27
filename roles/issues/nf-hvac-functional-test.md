> **PRIORITY: ASAP, owner directive.** Unify Open-FDD's three role vocabularies (input_contract.json, the #1808 manifest, the #1807 OpenAPI) on roles/openfdd-roles.json (strict ASHRAE 223P plus exact Haystack 4 mapping) before any other 5.0.22 rule work. Includes renaming \*_position inputs that are bound to command points, and fixing unit mismatches (0-1 vs %, L/s vs m3/s).

**Title:** Adopt Open-FDD `roles/openfdd-roles.json` for role ids, units, write ceilings and Haystack tag sets

## Problem

Paths refer to the open PR stack (scaffold through operator hooks). The role ids are the same in every PR.

- `lib/roles.js` defines 29 role ids, units and clamps by hand. Airflow is in m3/s (`lib/units.js` converts L/s to
  m3/s). `supply_fan_command` is `bool_or_percent`, so a start/stop command and a speed share one role.
- `schema/haystack-role-map.json` uses markers that are not in Haystack 4 (`ductStatic`, `flush`, `smoke`, `test`,
  `mode`), and puts an equipment marker (`ahu`, `vav`) on points. Fan status, freeze and smoke entries have no function
  marker. The airflow maximum lacks `sp`.
- `lib/model/haystack.js` lowercases every marker (`freezeStat` becomes `freezestat`) and folds the NF `class` into the
  tag set instead of matching it as a class. It picks the longest tag set rather than a strict superset, and only
  filters on `cmd`.
- `schema/rdf-role-map.json` uses local types instead of 223P classes.

Open-FDD 5.0.22 ships `roles/openfdd-roles.json` (89 roles; see its `README.md`) in the rules bundle. This app
consumes the 29 roles whose `consumers` include `nf-hvac-functional-test`.

## Renames, tag sets and units

Markers in *italics* are custom (declared in `haystack.custom_markers`). After the slash: forbidden markers.

| Old role | Canonical role | Old tags / forbid | Canonical markers (*custom*) / forbid | Unit |
|---|---|---|---|---|
| `discharge_air_temperature` | unchanged | discharge, air, temp, sensor / sp, cmd | discharge, air, temp, sensor | `DEG_C` |
| `mixed_air_temperature` | unchanged | mixed, air, temp, sensor / sp, cmd | mixed, air, temp, sensor | `DEG_C` |
| `return_air_temperature` | unchanged | return, air, temp, sensor / sp, cmd | return, air, temp, sensor | `DEG_C` |
| `outside_air_temperature` | `outdoor_air_intake_temperature` | outside, air, temp, sensor / sp, cmd | outside, air, temp, sensor / weather | `DEG_C` |
| `outside_air_relative_humidity` | `outdoor_air_intake_relative_humidity` | outside, air, humidity, sensor / sp, cmd | outside, air, humidity, sensor / weather | `PERCENT_RH` |
| `discharge_air_temperature_setpoint` | unchanged | discharge, air, temp, sp / max, min | discharge, air, temp, sp / max, min | `DEG_C` |
| `duct_static_pressure` | `discharge_air_static_pressure` | ductStatic, sensor / sp, cmd | discharge, air, pressure, sensor | `PA` |
| `duct_static_pressure_setpoint` | `discharge_air_static_pressure_setpoint` | ductStatic, sp / max, min | discharge, air, pressure, sp / max, min | `PA` |
| `supply_fan_run_status` | `supply_fan_operating_status` | supply, fan, run / cmd | fan, run, sensor / return, exhaust, pump | `boolean` |
| `supply_fan_command` | unchanged | supply, fan, cmd | fan, run, cmd / return, exhaust, pump | `boolean` |
| `outside_air_damper_position` | `outdoor_air_intake_damper_position` | outside, damper, sensor / cmd, sp | outside, damper, sensor | `PERCENT` |
| `return_air_damper_position` | `return_damper_position` | return, damper, sensor / cmd, sp | return, damper, sensor | `PERCENT` |
| `cooling_valve_position` | unchanged | cool, valve, sensor / cmd, sp | cool, valve, sensor | `PERCENT` |
| `heating_valve_position` | unchanged | heat, valve, sensor / cmd, sp | heat, valve, sensor / reheat | `PERCENT` |
| `outside_air_damper_command` | `outdoor_air_intake_damper_position_command` | outside, damper, cmd | outside, damper, cmd | `PERCENT` |
| `return_air_damper_command` | `return_damper_position_command` | return, damper, cmd | return, damper, cmd | `PERCENT` |
| `cooling_valve_command` | `cooling_valve_position_command` | cool, valve, cmd | cool, valve, cmd | `PERCENT` |
| `heating_valve_command` | `heating_valve_position_command` | heat, valve, cmd | heat, valve, cmd / reheat | `PERCENT` |
| `ahu_test_mode_command` | `test_operating_mode_command` | ahu, test, mode, cmd | cmd, *test*, *mode* | `enumeration` |
| `freeze_protection_status` | `air_temperature_low_limit_alarm_status` | freezeStat | freezeStat, sensor | `boolean` |
| `smoke_alarm_status` | `air_smoke_alarm_status` | smoke, alarm | alarm, sensor, *smoke* | `boolean` |
| `vav_max_cooling_mode_command` | `maximum_cooling_operating_mode_command` | vav, max, cool, cmd | max, cool, cmd, *mode* / sp, air, flow | `boolean` |
| `discharge_air_flow` | `discharge_air_volume_flow_rate` | air, flow, sensor / sp, cmd, max, min | air, flow, sensor / max, min, total | `L-PER-SEC` |
| `cooling_air_flow_setpoint` | `discharge_air_volume_flow_rate_setpoint` | air, flow, sp / max, min | air, flow, sp / max, min, total | `L-PER-SEC` |
| `cooling_air_flow_maximum` | `discharge_air_volume_flow_rate_maximum` | air, flow, max / sp, cmd, min | max, air, flow, sp / min | `L-PER-SEC` |
| `discharge_air_damper_position` | `damper_position` | discharge, damper, sensor / cmd, sp | damper, sensor / outside, return, exhaust, economizer, bypass | `PERCENT` |
| `zone_air_temperature` | unchanged | zone, air, temp, sensor / sp, cmd | zone, air, temp, sensor | `DEG_C` |
| `zone_air_temperature_setpoint` | unchanged | zone, air, temp, sp / max, min | zone, air, temp, sp (optional effective) / cooling, heating, occ, unocc, standby, max, min | `DEG_C` |
| `flush_mode_command` | `purge_operating_mode_command` | flush, cmd | purge, cmd / water | `boolean` |

## Unit and value changes

| Role | Today | After |
|---|---|---|
| `discharge_air_volume_flow_rate`, `discharge_air_volume_flow_rate_setpoint`, `discharge_air_volume_flow_rate_maximum` | m3/s | `L-PER-SEC`: L/s passes through, m3/s x1000, cfm x0.4719474432; scale the clamps x1000 |
| `supply_fan_command` | `bool_or_percent` | `boolean`; a 0-100 speed command binds `supply_fan_speed_command` (read only) |
| `test_operating_mode_command` | `enum` | `enumeration`; the site config lists the allowed values |
| `maximum_cooling_operating_mode_command`, `purge_operating_mode_command` | `bool_or_enum` | `boolean`: true enters the mode and false leaves it |
| status roles | `bool` | `boolean` |
| temperatures, pressures, ratios, humidity | `degC`, `Pa`, `%` | `DEG_C`, `PA`, `PERCENT`, `PERCENT_RH` (unit tokens only; values unchanged) |

## Writes

The roles file marks exactly these eight roles `writable: model`, and this app is their only writer:

- `outdoor_air_intake_damper_position_command`, `return_damper_position_command`, `cooling_valve_position_command`,
  `heating_valve_position_command` (the damper and valve commands)
- `discharge_air_volume_flow_rate_setpoint`
- `test_operating_mode_command`, `maximum_cooling_operating_mode_command`, `purge_operating_mode_command`

Every other role is read only, including `supply_fan_command` and `discharge_air_volume_flow_rate_maximum`. The
writer refuses any role whose `writable` is `never`, before the site allow-list and the runtime checks run. Clamps stay
inside the role `range`. An airflow write stays at or below the bound maximum.

## Haystack and RDF

- Replace `schema/haystack-role-map.json` with the `haystack` blocks from the roles file.
- In `lib/model/haystack.js`:
  - Read NF `class` as a class, and `markers` as one comma-separated string.
  - Keep marker case.
  - Require exactly one function marker per point.
  - Match `equip_markers` on the parent equipment.
  - Let a strict superset win; a remaining tie leaves the point unbound and reported.
- Replace `schema/rdf-role-map.json` with each role's `s223` basis: property class, medium, roles, aspects, quantity
  or enumeration kind, and equipment class.

## Pinning

Vendor `openfdd-roles.json` from the 5.0.22 rules bundle into `schema/`, record the tag and sha256, and load it in
`lib/roles.js`. Never fetch it at runtime. Until the bundle is published, vendor it from an Open-FDD commit SHA.

## What can't be patched now

- **Site tags.** Sites tagged the old way (`ductStatic`; fan status, freeze or smoke points without `sensor`; mode
  commands without the custom `mode` marker; `flush` instead of `purge`) stop binding by markers. They need retagging
  in NF, or an explicit point mapping in the site config. `npm run validate:examples` and the admin page must list
  every unbound required role with the markers it needs.
- **Site configs.** Existing configs use the old ids. The config loader maps them through `aliases` with a warning
  for one minor release, then rejects them.
- **The write-ahead ledger** holds entries under old ids. It stays as written (it is the audit trail), and the reader
  maps old ids through `aliases`.

## Drift CI to add

1. `test/roles-contract.test.js`:
   - the vendored file's sha256 equals the pin
   - the roles in `lib/roles.js` equal the file's roles whose `consumers` include this app
   - `direction` equals the `consumers` value
   - every write role is `writable: model`
   - units equal `unit`, and clamps stay inside `range`
2. A matcher test:
   - each role's own tag set binds exactly that role
   - a `max` airflow point never binds the airflow setpoint
   - a `cmd` damper point never binds a `*_position` role
   - a fan `run sensor` point never binds `supply_fan_command`
   - a camelCase marker (`freezeStat`) still matches
3. Add the retired ids from the table above to the `npm run scan` denylist: only old names that are not themselves
   canonical role ids. Leave unchanged canonical names (for example `discharge_air_temperature`) off the denylist, and
   exclude the alias reader.

## Acceptance criteria

- [ ] `lib/roles.js` carries no hand-written ids, units or clamps; it derives them from the vendored roles file.
- [ ] `schema/haystack-role-map.json` and `schema/rdf-role-map.json` are generated from, or replaced by, the roles
      file.
- [ ] Airflow is in L/s end to end, with clamps scaled. `supply_fan_command` is boolean.
- [ ] The writer refuses all 21 read-only roles. The tests cover `discharge_air_volume_flow_rate_maximum` and
      `supply_fan_command`.
- [ ] The matcher follows `haystack.binding_rules`, and the three drift tests pass in CI with lint, typecheck,
      coverage and the scan.

## Checklist of files

- [ ] `lib/roles.js`, `lib/units.js`, `lib/model/haystack.js`, `lib/model/map.js`, `lib/model/rdf.js`,
      `lib/model/writable.js`
- [ ] `schema/haystack-role-map.json`, `schema/rdf-role-map.json`, `schema/site-config.schema.json`, plus the vendored
      `schema/openfdd-roles.json`
- [ ] `lib/plan.js`, `lib/runner.js`, `lib/interlocks.js`, `lib/config/defaults.js`, `lib/vav/execute.js`,
      `lib/vav/airflow_setpoint.js`
- [ ] `examples/site-config.example.json`, `docs/DESIGN.md`, `docs/DECISIONS.md`
- [ ] Tests and fakes: `test/fake/ahu.js`, `test/fake/vav.js`, `test/helpers.js`, and `test/*.test.js` (`admin`,
      `config`, `fake`, `haystack`, `interlocks`, `machine`, `plan`, `release`, `roles`, `runner`, `vav`)
- [ ] `.github/forbidden-words.txt` (or a second denylist for retired role ids)
