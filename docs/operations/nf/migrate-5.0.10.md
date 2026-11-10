---
title: Upgrade to Open-FDD 5.0.10
parent: Operations
---

# Upgrade to Open-FDD 5.0.10

Full now creates one result point and one fault timeline for each sensor assessed by SV-STALE, SV-FLATLINE,
SV-RANGE, SV-SPIKE, or SV-RATE. Each point's identity uses the equipment, rule, and source point UUID.
The expected number of sensor result points is the sum of bound sensors over eligible equipment and sweep
rules. Timelines and equipment summaries are additional points.

The existing equipment result point remains the summary. Its value is the highest sensor fault hours, its
coverage is the highest sensor coverage, and its timeline flags intervals with any faulting sensor.
`fddSensorFaultHours` now maps source point UUIDs to `{role, name, hours, status}`. Read the sensor points'
`sensorRef` and `roleRef` attributes for current detail. The first successful run replaces stale result attributes
with current values or an empty value when an attribute does not apply.

SV-RATE now publishes fault hours. Existing sweep summary point histories can contain both percentages and hours
from earlier upgrades. The current output boundary is recorded in `fddOutputSince`. If an older result has no
recorded boundary, the first 5.0.10 sample sets it. The UI and analytics readers omit any resampling bucket that starts
before the boundary, including a bucket that spans it. A chart may therefore start after the first new sample.
Bucketed API readers should apply the same filter. The upgrade keeps the original NF history, and new sensor result
points start with hour-valued history.

Timescale schema v3 adds `sensor_ref` and `role` to `openfdd.fdd_results` and uses the primary key
`(run_ts, equip, rule_id, sensor_ref)`. Existing rows and new equipment summaries use an empty sensor reference.
Upgrade with `nf-app/timescale/install.sql` as the installer role before running the new hook with a
runtime-only role. The migration preserves the existing rows and can be run again.

Lite uses the same app version pin. Its dashboard and weather hook follow the existing upgrade procedure.
