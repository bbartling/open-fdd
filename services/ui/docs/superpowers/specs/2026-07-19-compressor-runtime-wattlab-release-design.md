# Vibe 19 Compressor Runtime and WattLab Export Design

## Scope

This release completes the mechanical-cooling runtime model in Vibe 19,
optimizes the Vibe 19 → Vibe 20 WattLab handoff, validates the Streamlit and
Docker experience, merges the green pull request into `develop`, and publishes
the established multi-architecture Vibe 19 GHCR image.

Vibe 19 remains responsible for BAS ingestion, role mapping, FDD, runtime
analytics, visualization, and handoff artifacts. Vibe 20 remains responsible
for consuming the handoff and running EnergyPlus/ECM workflows.

## Confirmed Current-State Problems

The baseline at commit `de53b47` already excludes chilled-water AHU valves and
restores an `ALL` device-hours series. The remaining problems are:

1. `mech_cooling_run_mask` returns no mask when a mapped proof stays off, so
   `mech_cooling_coverage` labels an eligible zero-runtime compressor as
   excluded and `mech_cooling_oat_bins` omits it.
2. Runtime is calculated as on-samples multiplied by one inferred poll period.
   It does not deterministically handle duplicate/irregular timestamps or cap
   long missing-data gaps.
3. The aggregate is only summed device-hours. There is no union-of-runtime
   any-compressor-active metric.
4. `mech_cooling_oat_histogram` renders the aggregate as another grouped bar.
   It lacks the requested semantic traces, proof-rich hover, and explicit
   one-running-device explanation.
5. `write_fdd_timeseries` loops over every result and copies plot/live telemetry
   into one CSV per result. The manifest has no export profile, stage timing, or
   serialization-count evidence.

## Mechanical-Cooling Domain Model

Add a normalized device record with stable fields:

- `equipment_id`, `equipment_type`, `cooling_technology`
- `compressor_based`, `included`, `eligibility_state`, `activity_state`
- `proof_quality`, `proof_role`, `proof_column`, `proof_threshold`
- `runtime_hours`, `valid_elapsed_hours`, `coverage_pct`
- `exclusion_reason`

Eligibility and activity are independent. A compressor device with valid mapped
proof that remains off is `eligible_no_runtime`, not excluded.

Chillers/CHW plants, explicitly DX AHUs/RTUs, cooling-mode heat pumps, VRF
outdoor units, and typed compressor equipment are eligible when acceptable
proof exists. Chilled-water valves, cooling demand, fan/pump status by itself,
and temperature response by itself do not prove a separate compressor device.
The existing opt-in CHW leaving-temperature inference remains clearly labeled
as inferred plant operation and is never applied to a chilled-water AHU valve.

Proof selection is deterministic and records the chosen source. Binary
compressor/chiller status precedes verified commands; stage statuses are ORed
for unit-active hours; compressor/chiller analog power/current uses
unit-aware configured thresholds. Heat-pump compressor status counts only when
cooling mode is proven. Technically defensible DX inference may be added only
when direct proof is absent and all required inputs persist; it remains labeled
`inferred`.

## Interval and Aggregate Semantics

Create one shared interval-duration utility:

1. sort timestamps and collapse duplicates deterministically;
2. calculate duration to the next timestamp;
3. cap duration by a configurable maximum gap derived from validated nominal
   cadence;
4. assign zero duration to the final row;
5. preserve timezone-aware indices;
6. expose valid elapsed duration and data coverage.

For each valid interval, calculate:

- individual device runtime;
- `aggregate_device_hours`: sum of every eligible device's runtime;
- `aggregate_active_hours`: elapsed duration where at least one eligible
  compressor is running.

The active-hours union aligns devices on interval boundaries without
double-counting simultaneous operation. Per-bin and overall invariants are
validated:

- device-hours equal the sum of individual hours;
- active-hours never exceed device-hours;
- active-hours never exceed valid elapsed observation hours.

## OAT-Bin Contract

Publish `wattlab_dump_v3` rows with explicit `series_kind` and stable
`series_id` while retaining legacy columns:

- `individual_device`
- `aggregate_device_hours`
- `aggregate_active_hours`

Keep `equipment_id`, `source`, `source_kind`, `bin_start`, `bin_label`, and
`hours`; retain `ALL` only as a compatibility identifier for device-hours.
Add bin bounds, equipment/proof metadata, device counts, sample counts, and
coverage.

Eligible zero-runtime devices remain in coverage but do not require zero-height
chart traces. Excluded devices remain in coverage with explicit state/reason.
Zero eligible devices produce a clear warning and do not crash.

## Streamlit and Plotly Design

Render individual device runtime as stacked bars. Render total compressor
device-hours as a marker line and any-compressor-active hours as a dashed marker
line. Aggregate metrics never participate in the device stack.

Trace names remain semantically distinct even when y-values match:

- the individual equipment label;
- `Total compressor device-hours`;
- `Any compressor active`.

Hover templates include equipment type, cooling technology, proof role/quality,
OAT bin, runtime, sample/coverage metadata, and aggregate device counts.
Coverage renders eligibility, activity, proof, runtime, and reason. When only
one device ran, the app explains why its value equals device-hours.

## WattLab Dump v3

Use CSV without adding `pyarrow`. Add three profiles:

- `summary` (default): manifest, maps/inventory, schedules/weather, mechanical
  cooling, runtime/sensor/setpoint/diurnal/model-seed statistics, FDD summaries,
  fault intervals, and minimal shared telemetry;
- `diagnostic`: summary plus FAULT/ERROR and user-selected rule evidence;
- `forensic`: broad applicable evidence and shared telemetry, while still
  suppressing known useless non-applicable/missing-role/equipment-off files.

Write normalized telemetry once per equipment under `telemetry/`, then make
small rule-evidence records refer to equipment, rule, time range, evidence
columns, intervals, and telemetry path. Do not serialize per-rule timeseries for
`NOT_APPLICABLE_EQUIPMENT_TYPE`, `SKIPPED_MISSING_ROLES`, or
`SKIPPED_EQUIPMENT_OFF`.

Extend sensor statistics with validity/missingness, time coverage, p01/p05/p25/
p50/p75/p95/p99, occupied/unoccupied and operating/off medians, flatline and
out-of-range percentages, units, source columns, equipment, and time bounds.
Observed values remain evidence with provenance/confidence, not unquestioned
design intent.

The manifest records profile, schema version, result-status counts,
applicable/non-applicable counts, files written/suppressed, compressed and
uncompressed bytes, and elapsed seconds by rule execution, analytics,
serialization, and compression. Vibe 20 receives compatibility tests for the
new package.

## Performance Measurement

Use the same deterministic fixture/package for before and after measurements.
Record elapsed time, file count, compressed/uncompressed bytes, per-rule
timeseries count, and suppressed combinations. The acceptance guard is semantic
rather than a promised percentage: default `summary` must not emit a Cartesian
product of rule/equipment evidence and must remain consumable by Vibe 20.

## Validation and Release

Implementation follows test-first red/green cycles and focused commits:

1. compressor classification, interval duration, and aggregates;
2. Plotly/Streamlit rendering and coverage UX;
3. WattLab v3 export profiles, shared telemetry, metrics, and compatibility;
4. documentation and measured evidence.

Validation includes focused tests, full Vibe 19 tests, affected Vibe 20 tests,
BUILDING_100 regression where the local fixture is available, AppTest, a real
browser with console/server-log inspection and screenshots, local Docker build
and browser smoke, and CI.

After the pull request is green, merge it into `develop`. Use only
`.github/workflows/vibe19-ghcr.yml` to publish `:develop`, `:latest`, and the
immutable SHA tag. Confirm amd64+arm64 manifest entries, pull the exact SHA image,
run it locally, repeat browser smoke, and record the digest. No Vibe 20 image is
updated by this work.

## Backward Compatibility

Existing CSV filenames and legacy OAT-bin columns remain. New consumers should
use `series_kind`, `series_id`, and coverage state. `wattlab_dump_v3` is an
additive schema transition with migration notes. Vibe 20 loader tests prove
both prior v2 and new v3 packages remain accepted.
