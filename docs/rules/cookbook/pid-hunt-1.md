---
title: PID-HUNT-1
parent: Rule Cookbook
nav_order: 11
permalink: /rules/cookbook/pid-hunt-1/
---

# PID-HUNT-1 — Suspected control-output hunting

**UI wording:** “Suspected control-loop hunting.” Output travel alone cannot prove bad PID tuning — unstable sequencing, safeties, overrides, or actuator problems can produce the same signature.

This rule is **not** a replacement for:

| Rule | What it measures |
|------|------------------|
| [FC4](datafusion-sql-cookbook.html#fc4--pid-hunting-operating-state-oscillation) | AHU **operating-mode** transition count (GL36-style) |
| [CTRL-2](datafusion-sql-cookbook.html#ctrl-2--generic-control-loop-hunting-duct-static) | **Process-variable** (e.g. duct static) direction reversals |

`PID-HUNT-1` measures **total distance traveled by a 0–100% control output** in a rolling one-hour window. Useful for any valve, damper, VFD, pressure-loop output, temperature-loop output, or other analog command.

**Canonical count:** treat as the **51st** independently useful FD rule (keep the prior 50; do not collapse into FC4).

Full implementations live in both cookbooks (never remove those sections):

- [DataFusion SQL — PID-HUNT-1](datafusion-sql-cookbook.html#pid-hunt-1--suspected-control-output-hunting)
- [Pandas — PID-HUNT-1](pandas-cookbook.html#pid-hunt-1--suspected-control-output-hunting)

## Core calculation

For output \(u_t\):

\[
\text{TotalVariation}_{1h}=\sum |u_t-u_{t-1}|
\]

Example:

```text
Signal:          0 → 100 → 0 → 100 → 0 → 100
Absolute moves:    100 + 100 + 100 + 100 + 100
Total variation:   500 percentage points
Observed span:     100 percentage points
Equivalent cycles: 500 / (2 × 100) = 2.5 cycles
```

Normalized metric:

\[
\text{EquivalentCycles}_{1h}
=\frac{\text{TotalVariation}_{1h}}{2 \times \text{ObservedSpan}_{1h}}
\]

Also detects mid-band hunting such as `40 → 60 → 40 → 60 → 40`.

## Recommended fault criteria

Do **not** use total variation alone. Require:

```text
Coverage during hour       ≥ 80%
Observed output span        ≥ 20 percentage points
Total variation             ≥ 300–500 percentage points/hour
Equivalent cycles           ≥ 2.5
Direction reversals         ≥ 4
Loop/equipment enabled      = true, when available
```

### Default parameters

```yaml
rule_id: PID-HUNT-1
window_minutes: 60
resample_seconds: 60
change_deadband_pct: 1.0
minimum_span_pct: 20.0
total_variation_fault_pct: 500.0
minimum_equivalent_cycles: 2.5
minimum_reversals: 4
minimum_coverage_pct: 80.0
minimum_samples: 48   # also derived from coverage × window/poll when not overridden
```

Extreme-crossing diagnostics (`low_extreme_pct` / `high_extreme_pct`) were removed — they were never part of the fault predicate.

The 500 threshold is a **severe-hunting starting point** and must remain tunable (hydronic valves may hunt 35–65% without hitting endpoints).

`window_minutes` is wired: runtime derives `WINDOW_ROWS = ceil(window_minutes * 60 / POLL_SECONDS)`.

## Roles

```yaml
required_roles:
  - control_output_pct
optional_roles:
  - loop_enabled
  - process_value
  - setpoint
  - control_error
equipment_types:
  - ANY
operational_gate:
  mode: CONDITIONAL
  predicate: loop_enabled
  preferred: loop_enabled
```

### Enable / null policy

| Case | Behavior |
|------|----------|
| `loop_enabled` role absent | Treat as enabled (no restriction); runner injects `TRUE` |
| Column present, cell NULL | Disabled (`fillna(0)` / SQL `COALESCE(>0, FALSE)`) |
| Column present, value &gt; 0 | Enabled |

### Normalization

Analog outputs: if value ≤ 1.5 treat as 0–1 fraction and scale ×100; clip to inclusive `[0, 100]`; preserve nulls.

### Reversals

Direction uses significant deltas only. Zero/deadband rows carry forward the last significant direction (Pandas `ffill` / SQL `LAST_VALUE … IGNORE NULLS`) so `+1, 0, -1` counts as one reversal.

## Shipped SQL registry

| Field | Value |
|-------|-------|
| `rule_id` | `PID-HUNT-1` |
| `sql_file` | `pid_hunt_1.sql` |
| SQL output | `equipment_id`, `fault_hours` (aggregate only) |
| Status mapping | Runner / API layer (`PASS` / `FAULT` / `SKIPPED_*`) — **not** emitted by the SQL file |
| Cookbook mapping | this page + both expression cookbooks |

See [COOKBOOK_TO_SQL_RULES](../../cookbook/COOKBOOK_TO_SQL_RULES.md) and [operational gates](operational-gates.html).
