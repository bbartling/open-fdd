---
title: FCU and zone_other rules
parent: Rule Cookbook
nav_order: 12
---

# Fan-coil and standalone zone-controller rules

Open-FDD ships nine **FCU-*** rules for fan coils and standalone DDC zone
controllers. They run in the DataFusion product engine and in the external
`open_fdd.rules` pandas oracle. Per-rule equations, parameter tables, and the
shipped SQL / pandas are in the
[DataFusion SQL cookbook](datafusion-sql-cookbook.html#fan-coil--zone_other)
and the [Pandas cookbook](pandas-cookbook.html#fan-coil--zone_other). This page
is the unit-boundary and equipment-kind deep dive.

Registry equipment kinds are `zone_other`, `general`, and `ahu`
(`sql_rules/registry.yaml` and `CookbookRule` in
`open_fdd/rules/cookbook_catalog.py`). Stamps `zone_other`, `zone`, `fcu`,
`fanCoil`, `fanCoilUnit`, and the standalone-DDC aliases canonicalize to
`zone_other` (`edge/src/equipment_types.rs`).

Haystack tags stack on one record: an equip carries `equip` + `fanCoilUnit` +
`zone` together, and each point carries its own markers (`zone` + `air` +
`temp` + `sensor`, `discharge` + `air` + `temp`, `heating` + `valve` + `cmd`,
and so on). Open-FDD consumes that stack as **one stamp** plus the **flattened
point-role map** (`zone-air-temp`, `discharge-air-temp`, `heating-valve`, …).
The equipment id is only the historian key. Master versus follower is the
stamp (`zone_other` versus resolved kind `general`) together with whether
`zone-air-temp` is mapped. Detail:
[Zone terminals]({{ site.baseurl }}/modeling/zone-terminals/).

| Rule | Screening condition | Confirm |
| --- | --- | ---: |
| `FCU-SENSOR-NULL` | Own zone SP exists and zone temperature is null for at least 90% of the window | 0 |
| `FCU-HTG-COIL` | Fan on, heating ≥80%, SAT − zone <5.4°F | 15 min |
| `FCU-CLG-COIL` | Fan on, cooling ≥80%, heat shut, SAT ≥ zone | 15 min |
| `FCU-VALVE-PASS-HTG` | Fan on, both valves shut, SAT − zone >5.4°F | 15 min |
| `FCU-VALVE-PASS-CLG` | Fan on, both valves shut, zone − SAT >5.4°F | 15 min |
| `FCU-DAMPER-POS` | Fan on, command ≥15%, feedback >15 points low | 15 min |
| `FCU-CO2-DAMPER` | Fan on, valid CO₂ >1000 ppm, damper command <10% | 15 min |
| `FCU-DEADBAND` | Cooling SP − heating SP <1°C | 0 |
| `FCU-MODE-CYCLE` | At least four heat/cool valve mode transitions in the window | 0 |

## Equipment kinds

| Controller | Stamp (`equipType` / `equipment_type`) | Registry kind |
| --- | --- | --- |
| Sensor-owning fan coil or standalone zone controller (master) | `zone_other`, `zone`, `fcu`, `fanCoil`, `fanCoilUnit`, or a standalone-DDC alias | `zone_other` |
| Follower with no zone sensor of its own | registry kind `general` (see below) | `general` |
| Stamped air handler that also carries these roles | `ahu` and the AHU aliases | `ahu` |

A fan coil's stamp stays on the `zone_other` row. Stamping it `ahu` sends it
down the air-handler path. `ahu` remains on the FCU registry list so an air
handler can run this family when the roles are mapped. Modeling detail:
[Zone terminals, FCU, and unit ventilators]({{ site.baseurl }}/modeling/zone-terminals/).

`canonical_kind` in `edge/src/equipment_types.rs` resolves the master stamps
above to `zone_other`. It does not list the token `general`. Product results
call `kind_for`, which returns `zone_other`, `ahu`, or another canonical kind.
The registry still lists `general` so a follower kind matches the family where
that kind is actually resolved (the pandas oracle maps a `GENERAL` type to
`general`). Pair a setpoint-only follower with the sensor-null behavior below
rather than an equipment-id test.

`FCU-SENSOR-NULL` treats a missing `zone_t` column as zero fault hours. The
runner rewrites `sql_rules/fcu_sensor_null.sql` in that case so a follower that
only publishes a setpoint is not a dead-sensor fault. A present `zone_t`
column that is null still runs the coverage test. The pandas twin returns an
all-false mask when `zone-air-temp` is not a column.

## Roles

Haystack tags are the preferred `haystack_point_to_role` arms in
`crates/fdd_core/src/columns.rs`. The full registry table is
[SQL rules → Haystack map]({{ site.baseurl }}/modeling/sql-rules-haystack-map.html).

| SQL role | Haystack tag | Used by |
| --- | --- | --- |
| `zone_t` | `zone-air-temp` | sensor-null (optional), coils, passing valves |
| `zone_air_temp_sp` | `zone-air-temp-sp` | `FCU-SENSOR-NULL` (required) |
| `sat` | `discharge-air-temp` | coils, passing valves |
| `htg_valve_pct` | `heating-valve` | heating coil, both passing-valve rules, cooling coil, mode cycle |
| `clg_valve_pct` | `cooling-valve` | cooling coil, both passing-valve rules, mode cycle |
| `damper_cmd` | `damper-cmd` | damper position, CO₂ damper |
| `damper_pct` | `damper` | damper position |
| `zone_co2` | `zone-co2` | CO₂ damper |
| `cooling_sp` | `cooling-sp` (alias `zone-cooling-sp`) | deadband |
| `heating_sp` | `heating-sp` (alias `zone-heating-sp`) | deadband |
| `fan_status` | `fan-status` | fan proof (optional) |
| `fan_cmd` | `fan-cmd` | fan-proof fallback (optional) |

Commands accept either 0–1 or 0–100 values (`> 1.0` divides by 100). Fan proof
prefers status. CO₂ below 300 ppm is treated as invalid rather than a
ventilation fault. Valve-shut tests use a fixed 0.05.

### Fan-proof screening difference

DataFusion (`sql_rules/fcu_*.sql`): when `fan_status` is not null, on means
`fan_status > 0.05`; otherwise normalized `fan_cmd > 0.10`.

Pandas (`_fcu_fan_on`): when `fan-status` is non-null, `as_bool` treats a
numeric status as on above `0.5`; null samples fall back to `fan-cmd > 0.10`.

That cut is one reason the family remains `sql_screening`.

## Unit boundary

Canonical FDD temperatures are °F. `sat` and `zone_t` are in
`TEMPERATURE_ROLES` (`crates/fdd_core/src/units.rs`). On a metric or SI
session the DataFusion engine reads them from `history_si`, converted to °F,
so coil and passing-valve deltas are °F (default 5.4°F = 3°C).

`cooling_sp`, `heating_sp`, and `zone_air_temp_sp` are not temperature roles.
`history_si` does not convert them. `FCU-DEADBAND` compares `cooling_sp −
heating_sp` in site-native °C (`deadband_c`, default 1). Package authors must
not map Fahrenheit setpoints into `cooling_sp` or `heating_sp`.

The pandas runner drops `zone-air-temp-sp`, `cooling-sp`, and `heating-sp`
from the Fahrenheit quality pass for every `FCU-*` rule so those ranges do
not null the pass-through columns before `FCU-DEADBAND` or `FCU-SENSOR-NULL`.

## Loading and evidence

The files live in `sql_rules/` and are registered in
`sql_rules/registry.yaml`; no site registry fork or
`OPENFDD_SQL_RULES_DIR` override is needed. Registry `parity_status` is
`sql_screening`. Focused predicate fixtures cover pandas behavior, and
DataFusion SQL is compiled and executed by Rust rule tests. That is not mask
or duration proof.

Soft-OPEN for this family closes only after tip and field stress on
issue-mapped gates (mask and duration versus the pandas oracle). Cookbook CI
and a green docs build do not close it. There is no FCU gate in the stress
scripts yet; adding that stub is a later change, not part of the cookbook
pages. The `dashboard_wired` field remains false while these rules are outside
the maintained Overview summaries; the Results and SQL FDD surfaces still
expose their registry entries.
