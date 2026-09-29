# Overview health API contracts

Backend Overview health matrices are building-scoped `POST /api/analytics/*` endpoints using the standard analytics request envelope.

**RCx Plotly presets (by HVAC type)** live on **RCx Plots** (`/rcx`), not Overview — see [`RCX_PLOTS_BY_HVAC.md`](RCX_PLOTS_BY_HVAC.md).

## Matrix endpoints

- `/api/analytics/ahu-temperature-health`
- `/api/analytics/ahu-pressure-health`
- `/api/analytics/ahu-economizer-health`
- `/api/analytics/chiller-health`
- `/api/analytics/cooling-tower-health`
- `/api/analytics/pid-hunting`
- `/api/analytics/sensor-faults`

Existing `/api/analytics/ahu-health`, VAV, heat-pump, boiler, and weather-facing contracts remain available for compatibility while Overview adopts the split matrices.

## Matrix row contract

Health specs accept arbitrary-length flag vectors. Every row includes `dimensions_hit`, `dimensions_evaluable`, `dimensions_total`, and `score_label`. A fully evaluable row is scored `n/m`; incomplete evidence is `?/m`. Each flag keeps its boolean/null value and `{flag}_fault_h`; `total_fault_h` sums only faulting dimensions.

Equipment classification uses the persisted package type stamp. A missing or unrecognized stamp is unclassified; equipment-id text is not a kind. Do not add `LIKE`, prefix, or name filters. Cooling towers stay `cooling_tower` when that stamp is present, separate from chillers.

## Sensor clean-state contract

`/api/analytics/sensor-faults` is faults-only. When sensor validation results are present and none of the `SV-*` rules fault, the endpoint deliberately returns `rows: []`. The React Overview should render its Sensor section shell and show the clean-state message rather than hiding the section.
