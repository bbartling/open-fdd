---
title: Water & chiller FDD priority
parent: Rule Cookbook
nav_order: 1
permalink: /rules/water-chiller-fdd-priority/
---

# Water-system & chiller-plant FDD — research priority (#1009)

Research backlog for **deterministic, Haystack-oriented** fault detection on commercial **chilled-water**, **condenser-water / cooling-tower**, and **hot-water / hydronic** loops. Equipment is selected by **`equipType` / registry `equipment_kinds`** and mapped **SQL roles** — never by vendor name, device instance, or substring match on `equipment_id`.

**Parity honesty:** Rules listed here that already appear in [`sql_rules/registry.yaml`](https://github.com/bbartling/open-fdd/blob/master/sql_rules/registry.yaml) and the [DataFusion](cookbook/datafusion-sql-cookbook.html#central-plant--condenser-water) / [Pandas](cookbook/pandas-cookbook.html#central-plant--condenser-water) cookbooks are **`sql_screening`** catalog entries. **Do not claim Pandas↔SQL predicate, mask, or duration parity** until executable fixtures pass the levels in the [parity matrix](cookbook/parity-matrix.html). Plant rules are documented in both catalogs; that is not oracle proof.

**Related framework docs:** [taxonomy](cookbook/taxonomy.html) (`plant.chw`, `plant.hw`, `plant.tower`), [gap matrix](cookbook/gap-matrix.html), [roadmap](cookbook/roadmap.html), [P0 rule catalog](cookbook/p0-rule-catalog.html).

---

## What exists today (central plant / CW)

Eight **plant-family** diagnostics are in the validated cookbook inventory ([cookbook index](cookbook/index.html#rule-inventory-validated)):

| Rule ID | Concept | Registry `equipment_kinds` | Required roles (minimum) | Notes / gaps |
|---------|---------|----------------------------|--------------------------|--------------|
| `CHW-NOLOAD-1` | Chiller/plant running while building load satisfied | `chiller` | *(none — uses optional proof)* | Optional: `chiller_status`, `chiller_cmd`, `chw_pump_*`, `building_zone_load_satisfied`, `building_ahu_load_satisfied`. On **Wave 1 parity backlog** ([parity matrix](cookbook/parity-matrix.html)). |
| `CHW-1` | Low CHW ΔT | `chiller` | `chw_supply_t`, `chw_return_t` | Fixed default `min_dt` (4°F); should gate on **pump/chiller proof** and prefer **load/flow context** when mapped (`chw_flow`, `chiller_power`, …). |
| `CHW-2` | Low CHW DP at high pump speed | `chiller` | `chw_dp`, `chw_dp_sp`, `chw_pump_cmd` | Does not yet require downstream **demand evidence** (valve/flow); complements state-aware DP rules below. |
| `CHW-3` | CHW supply outside SP deadband | `chiller` | `chw_supply_t`, `chw_supply_sp`, `chw_pump_cmd` | Capacity vs control fault — distinguish low load and staging transitions in follow-ups. |
| `CHW-4` | High CHW flow at max pump | `chiller` | `chw_flow`, `chw_pump_cmd` | Default `flow_hi` (1100 gpm) is **site design**, not universal; must be parameterized per plant. |
| `CW-OPT-1` | CW colder than WB + design approach (over-cooling) | `chiller`, `cooling_tower` | `cw_supply_t` (+ web wet-bulb) | **Opportunity / advisory** bias vs hard fault. |
| `CW-APR-1` | High tower approach at high fan speed | `chiller`, `cooling_tower` | `cw_supply_t` (+ web WB, fan proof optional) | Capacity / fouling / sensor bias confounders. |
| `CW-FAN-1` | Full tower fan, CW still hot vs WB + approach | `chiller`, `cooling_tower` | `cw_supply_t` (+ web WB) | Overlaps `CW-APR-1` / proposed `TOWER-1` — see overlap decision below. |

**Adjacent (not plant-family but water-loop relevant):**

| Rule ID | Family | Applies to | Water relevance |
|---------|--------|------------|-----------------|
| `FC14` | AHU | `ahu` | CHW coil ΔT when coil should be inactive (terminal hydronics). |
| `MECH-OAT-1` | AHU | `ahu`, `chiller`, `heatpump` | Mechanical cooling proof — uses chiller/compressor roles, not valve-only. |
| `TRIM-4` | Trim | `chiller` | CHW supply vs low `chw_reset_request_sum` — reset **advisory**. |
| `TRIM-3` | Trim | `boiler` | HW supply vs low `hw_reset_request_sum` — only shipped **HW trim** rule today. |
| `SV-*`, `PID-HUNT-1`, `SCHED-247` | Sensor / control / schedule | includes `chiller`, `boiler` | Run when plant points are mapped; not plant-performance-specific. |

**Documented but not in validated catalog:** `PLANT-1` (CHW DP reset missing), `TOWER-1` (tower approach — flagged in [gap matrix](cookbook/gap-matrix.html)), lead-lag staging, waterside economizer ([roadmap](cookbook/roadmap.html)).

---

## Role map (Haystack → registry)

Stamp plants with recognized kinds (`chiller`, `cooling_tower`, `boiler` / `chwPlant` / `hotWaterPlant` per [taxonomy](cookbook/taxonomy.html)). Bind points to generic roles (see [SQL rules → Haystack map]({{ site.baseurl }}/modeling/sql-rules-haystack-map.html)).

| Theme | Typical roles | Sufficiency |
|-------|---------------|-------------|
| CHW loop temps | `chw_supply_t`, `chw_return_t`, `chw_supply_sp` | ΔT and supply tracking rules |
| CHW hydraulics | `chw_dp`, `chw_dp_sp`, `chw_flow`, `chw_pump_cmd`, `chw_pump_status`, `pump_status` | DP, flow, pump-off checks |
| Chiller proof | `chiller_status`, `chiller_cmd`, `chiller_amps`, `chiller_current`, `chiller_power` | Running state, noload, staging |
| Evaporator / condenser | `chw_*`, `cw_supply_t`, `cw_return_t`, per-machine LWT/EWT where mapped | Approach, header disagreement (future) |
| Tower | `tower_fan_cmd`, `tower_fan_status`, `cw_supply_t` | Approach, fan saturation |
| Building load proxy | `building_zone_load_satisfied`, `building_ahu_load_satisfied`, terminal valves / SAT | `CHW-NOLOAD-1`, load-gated ΔT |
| HW loop | `hw_supply_t`, `hw_return_t`, `hw_supply_sp`, `hw_pump_cmd`, `hw_reset_request_sum` | Boiler trim today; HW performance backlog |
| Weather | `web-outside-air-temp`, calculated wet-bulb | CW rules, future reset checks |
| Bypass / mode | `chw_bypass_valve`, `min_flow_bypass`, plant mode (future) | Low-flow + bypass saturated |

Optional roles in registry should stay **optional** — rules must **fail closed** (no fault) when proof signals are missing, not guess from unrelated columns.

---

## Source anchors (research leads — verify current editions)

| Source | Use for Open-FDD backlog |
|--------|---------------------------|
| ASHRAE Guideline 36 (2018 addendum x public PDF; **confirm against G36-2024** before claiming “G36-aligned”) | State-gated plant faults: flow/DP when pumps off, min-flow bypass, supply/pressure, evaporator/condenser approach, sensor disagreement, tower limits, excessive starts, stage churn + **delays after stage changes**. |
| NIST HVAC-Cx chilled-water study | Expert rule patterns vs field BAS data — prioritization and false-positive patterns. |
| ASHRAE Guideline 22-2025 | Instrumentation for plant load, energy, efficiency — minimum metering before **kW/ton / COP** advisories. |
| DOE FDD test datasets & prioritization | Ground-truth fixtures, varied conditions, O&M alert ranking — separate **literature coverage** from **field prevalence**. |
| Berkeley / PNNL / AIRCx (via [gap matrix](cookbook/gap-matrix.html)) | Cross-check terminal and reset themes already covered elsewhere. |

---

## Overlap decisions (avoid duplicate rule IDs)

| Proposed / roadmap ID | Existing coverage | Recommendation |
|----------------------|-------------------|----------------|
| `TOWER-1` | `CW-APR-1`, `CW-FAN-1` | **Do not add** a third identity for “high approach at high fan” without a **distinct fault signature** (e.g. approach high at **low** fan = free-cooling / sensor issue). Prefer **extending parameters/gates** on `CW-APR-1` / `CW-FAN-1` or one merged tower-capacity rule with explicit sub-modes. |
| `PLANT-1` | `CHW-2`, `TRIM-4`, `RESET-1` (AHU SAT only) | **Distinct:** missing **CHW DP reset** vs low DP at max speed (`CHW-2`). Implement as new rule when reset SP trace + pump speed available. |
| Low CHW ΔT | `CHW-1` | **Evolve `CHW-1`** with load/flow gates rather than new ID unless signature splits (e.g. overflow vs low load). |

---

## Prioritized backlog

Priorities rank **implementation follow-ups** (registry + both cookbooks + fixtures). Each item should become its own GitHub issue when accepted — not bulk-implemented from this doc alone.

### P0 — harden catalog, parity, and scaling (do first)

| ID / theme | Type | Required / optional roles | Detection concept | Gates & confounders |
|------------|------|---------------------------|-------------------|---------------------|
| Plant rule **parity proofs** | Engineering | Per rule above | Promote from `sql_screening` only with predicate/mask/duration fixtures | Start with `CHW-NOLOAD-1` (already Wave 1) |
| **`CHW-1` load-aware ΔT** | Refine existing | Required: `chw_supply_t`, `chw_return_t`; optional: `chw_flow`, `chiller_power`, `chiller_status`, `chw_pump_cmd` | Low ΔT only when **hydraulic cooling delivery** is plausible (pump/chiller on, optional min flow or load proxy) | Low load, bypass/decoupler flow, sensor swap |
| **`CHW-4` design-scaled flow** | Refine existing | `chw_flow`, `chw_pump_cmd`; optional design metadata | High flow vs **site max** or % of design, not fixed gpm default | Variable-primary, staging |
| **`CHW-2` / `CHW-3` complement doc + gates** | Refine existing | As registry | Document when DP vs SP faults fire; add optional **terminal demand** roles in follow-up | Primary-only vs secondary, DP sensor location |
| **State: flow or DP when pumps commanded off** | New (`CHW-OFF-FLOW-1` candidate) | `chw_pump_cmd`, `chw_flow` and/or `chw_dp` | Residual flow/DP above noise when all mapped pumps off | Standby heat expansion, sensor zero bias |
| **State: low primary flow + min-flow bypass saturated** | New (`CHW-MINFLOW-1` candidate) | `chw_flow`, bypass valve position or pump speed proof | Flow below minimum while bypass fully open (G36 lead) | Staging, valve mapping errors |

### P1 — high-value new plant diagnostics

| ID / theme | Type | Required / optional roles | Detection concept | Gates & confounders |
|------------|------|---------------------------|-------------------|---------------------|
| **`PLANT-1` — CHW DP reset missing** | New (roadmap) | `chw_dp_sp`, `chw_pump_cmd`, load proxy or OAT | SP not tracking reset schedule while load varies | Fixed-primary plants without reset |
| **Chiller **evaporator / condenser approach**** | New (`CHLR-APR-1` candidate) | Machine LWT/EWT vs header `chw_*` / `cw_*` | Approach high vs design at rated conditions | Part-load, false LWT sensor |
| **Header vs machine sensor disagreement** | New (`CHLR-SENSOR-1` candidate) | Duplicate temp roles on header vs chiller | \|ΔT\| above tolerance when both trusted | Calibration drift, lag during ramp |
| **Excessive starts / stage churn** | New (`CHLR-STAGE-1` candidate) | `chiller_status` or stage enum | Start count or state changes per hour above limit | **Startup/stage delay** suppression (G36) |
| **Low system pressure** | New (`CHW-PRESS-1` candidate) | `chw_system_pressure` or DP at boundary | Pressure below SP − band with pumps on | Sensor elevation, closed isolation |
| **Tower: distinguish capacity fault vs optimization** | Refine CW family | `cw_supply_t`, fan cmd/status, web WB | Keep **`CW-OPT-1`** as opportunity; **`CW-APR-1` / `CW-FAN-1`** as capacity | Wet-bulb source, OA sensor used as WB |

### P2 — HW plant, economizer, efficiency, staging

| ID / theme | Type | Required / optional roles | Detection concept | Notes |
|------------|------|---------------------------|-------------------|-------|
| **HW low ΔT (symmetric to `CHW-1`)** | New (`HW-1` candidate) | `hw_supply_t`, `hw_return_t`, pump/boiler proof | Low ΔT with heating delivery plausible | Condensing boiler return temp opportunities separate |
| **HW pump cmd/status/flow mismatch** | New | `hw_pump_cmd`, `pump_status`, `hw_flow` or `hw_dp` | Same pattern as `CMD-1` / hydraulics | |
| **Boiler short cycling / lead-lag** | New | `boiler_status`, stage commands | Cycles per hour, unstable lead-lag | Pattern library ([gap matrix P3](cookbook/gap-matrix.html)) |
| **HW DP reset missing** | New | `hw_dp_sp`, load/OAT | Mirror `PLANT-1` on hot side | |
| **Waterside economizer** | New | Mode enum, HX approach, isolation valves | Eligibility + performance when in economizer mode | Suppress during mode transitions |
| **Plant kW/ton or COP advisory** | Analytics / trim | `chw_flow`, CHW ΔT, `electric_kw` / `kwh`, stable meters | Efficiency vs expected curve | **Not a fault** without Guideline 22-grade metering; minimum data sufficiency table in issue |
| **Cooling tower makeup / blowdown** | Analytics | Makeup meter, basin level | Water use anomaly | Often BMS-specific — keep optional |

---

## Cross-cutting implementation requirements (all priorities)

For each accepted rule follow-up:

1. **Equipment kinds:** `chiller`, `cooling_tower`, `boiler` as applicable — no campus or vendor ids in SQL.
2. **Operating state:** explicit pump/chiller/boiler proof macros ([prerequisite macros](cookbook/prerequisite-macros.html)); **stage-change and startup delays** for plant transitions.
3. **Fault vs advisory:** label trim/optimization rules (`TRIM-*`, `CW-OPT-1`, future efficiency) separately from **confirmed faults**.
4. **Fixtures:** positive, negative, boundary, low-load, stage transition, missing NULL roles, and sensor-quality cases per [benchmark strategy](cookbook/benchmark-strategy.html).
5. **Dual catalog:** update registry, SQL file, Pandas oracle, generated inventory, and parity tests **together**; bump parity status only after proofs pass.

---

## Recommended follow-up GitHub issues (titles only)

Create **one issue per rule or coherent bundle** when pulling from this backlog — examples:

- `CHW-1: load- and flow-gated low delta-T`
- `CHW-4: replace absolute gpm default with design-scaled threshold`
- `CHW-OFF-FLOW-1: residual CHW flow/DP with pumps off`
- `PLANT-1: CHW differential-pressure reset not tracking load`
- `CHLR-APR-1: chiller evaporator/condenser approach high`
- `CHLR-STAGE-1: excessive chiller starts with stage-delay suppression`
- `HW-1 / HW hydraulics bundle for boiler plants`
- `Plant rule parity fixtures: CHW-NOLOAD-1, CHW-1, …`

---

## Non-goals

- **Vendor-specific** sequences, proprietary point names, or threshold bundles tied to one OEM.
- **Hardcoded** plant design constants in product code (e.g. universal 1100 gpm) without site sliders or package metadata.
- **Building/campus/equipment_id substring** selection — type stamp and roles only.
- **ML / black-box** anomaly models — stay deterministic SQL + Pandas oracle.
- **Claiming Pandas↔SQL parity** for plant rules without executable proof.
- **Root-cause diagnosis** from a single symptom — rules surface **symptoms** with documented false-positive cases.
- **Full hydronic distribution network modeling** (every terminal valve) in v1 plant rules — use load proxies and mapped terminals where available.

---

## Document history

| Date | Change |
|------|--------|
| 2026-10-03 | Initial research priority for #1009 (PR-04). |
