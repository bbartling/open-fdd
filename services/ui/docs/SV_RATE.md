# SV-RATE — Context-Aware Sensor Rate of Change

**Rule ID:** `SV-RATE` (alias `SV-SLEW`)  
**Family:** sensor validation  
**Purpose:** Flag sensors whose engineering value changes at an implausible sustained rate while
avoiding false alarms during legitimate HVAC startup, shutdown, staging, and mode changes.

## Not the same as

| Rule | Failure mode |
| ---- | ------------ |
| `SV-RANGE` | Value outside hard physical range |
| `SV-FLATLINE` | Stuck / unchanging sensor |
| `SV-SPIKE` | One-sample jump |
| `PID-HUNT-1` | Oscillating control output |

## How thresholds are chosen

Thresholds depend on (1) quantity, (2) location/role, (3) equipment type, (4) operating state
(steady vs transient), (5) time since transition, (6) sampling/data quality, (7) unit system for
display, and (8) design flow / sensor span when required for flow profiles.

Defaults live in `app/rules/sensor_rate_profiles.py` and are **configurable engineering screening
values — not universal code limits**. Tune them per site.

Temperature rates are authored in °F/h; Δ°C = Δ°F × 5/9 (no 32° offset). Air pressure rates are
stored as Pa/h from in.w.c./h. Hydronic rates are stored as kPa/h from psi/h.

## Operating state

Reuse / mirror plant proofs (`fan-status`, pump status, valve / OA damper moves). Intervals class
as `OFF`, `STARTUP_TRANSIENT`, `SHUTDOWN_TRANSIENT`, `RUNNING_STEADY`, or `UNKNOWN_STATE`. Missing
state signals use steady thresholds with **reduced confidence** — they do not auto-fail.

Design notes (not copied from copyrighted text): ASHRAE G36 evaluates AHU AFDD by operating state
with delays; FDD literature separates transient vs steady periods; ASHRAE 55’s hourly operative-
temperature drift is only a conservative zone-temperature screening reference; ASHRAE 62.1 CO₂
language covers accuracy/placement/failure handling, not a universal ppm/h rate.

## Streamlit

**Run Rules → SV-RATE expander:** grouped profile table editors, persistence / transition window,
missing-state fallback, restore defaults, export JSON, resolved-profile peek for the selected
equipment.

## Known limitations

- Demo frames are assumed imperial for pressure; conversion to Pa/kPa happens inside the rule.
- Adaptive (MAD) baseline mode is not enabled in v1.
- Flow profiles skip when neither design flow nor sensor span is configured.
