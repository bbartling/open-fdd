---
title: SQL anomaly detection
parent: Rule Cookbook
nav_order: 2
permalink: /rules/sql-anomaly-detection/
---

# SQL anomaly detection

Open-FDD ships **two** anomaly-style layers. Do not conflate them:

| Layer | What it is | Where you see it | Tuners |
|-------|------------|------------------|--------|
| **Overview SQL anomaly screening** | Statistical self-baseline (rolling Z-score / robust) on mapped sensors | Overview → **Anomaly screening (SQL)** | Request `series` params (not Lab rule sliders) |
| **Registry rules (`SV-*`, `PID-HUNT-1`, `WX-1`)** | Deterministic physics / quality / hunting screens in DataFusion SQL | Lab → **SQL FDD Rules** → Run all / FDD Plots · plant health matrices | Lab sliders from [`sql_rules/registry.yaml`](https://github.com/bbartling/open-fdd/blob/master/sql_rules/registry.yaml) |

Neither layer is ML or peer-fleet scoring. Peer / self-baseline expansion beyond the Overview screen remains optional follow-on work.

---

## 1. Overview SQL anomaly screening (Wave M / soft-OPEN)

**Purpose:** Flag equipment × sensor roles whose recent samples deviate from their own recent distribution — useful when hard physics limits are still “in range” but the point is behaving oddly.

**Engine:** DataFusion over historian Parquet (`POST /api/analytics/sql-anomaly`, `query_version: sql-anomaly-v1`).

**UI:** React Overview section `data-testid="overview-sql-anomaly"` — tabulated only (no Plotly).

**Hub flag:**

| Env | Default | Meaning |
|-----|---------|---------|
| `OPENFDD_SQL_ANOMALY_SCREENING` | **on** when unset | Set `0` / `false` / `off` on live OT hubs that should skip the scan |
| Status | — | `GET /api/analytics/sql-anomaly/status` → `{ enabled, mode }` |

### Screened roles

Only columns present in the building’s historian are screened:

`oa_t`, `mat`, `sat`, `zone_t`, `zone_rh`, `duct_static`, `oa_h`

(Package maps must expose these SQL roles — see [package authoring]({{ site.baseurl }}/agent/PACKAGE_AUTHORING.html) / Haystack → SQL.)

### Methods

| `series.method` | Behavior |
|-----------------|----------|
| `zscore` (default) | Rolling mean / stddev over `window_rows`; flag when `\|z\| > z_threshold` |
| `robust` | Per-equipment median + population σ (MAD-style soft fallback); same threshold on robust z |

### Request tuners (`series` object)

Overview currently posts the defaults below. Agents / API clients may override:

| Key | Type | Default | Clamp / notes |
|-----|------|---------|---------------|
| `window_rows` | u32 | `24` | Clamped **3–168** (hours-ish samples; depends on poll) |
| `z_threshold` | f64 | `3.0` | Clamped **1–10** |
| `method` | string | `"zscore"` | `"robust"` for the median/σ path |
| `transition_events` | bool | `true` | Counts normal→anomaly edges into `anomaly_events` |

**Output columns:** `equipment_id`, `role` (Haystack-ish), `method`, `score` (max \|z\|), `threshold`, `anomaly_hours` (≈ flagged sample count), `anomaly_events`, `last_at`.

**Example:**

```bash
curl -sS -X POST "$OPENFDD_API_BASE/api/analytics/sql-anomaly" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "building_id": "ACME",
    "query_version": "sql-anomaly-v1",
    "series": {
      "window_rows": 48,
      "z_threshold": 2.5,
      "method": "zscore",
      "transition_events": true
    }
  }'
```

There is **no Lab slider strip** for this analytics path today — tune via Overview defaults or the API `series` body. After **Update this rule** on registry rules, Overview still refreshes its own anomaly table on building / refresh token only.

---

## 2. Sensor validation rules (`SV-*`) — Lab tuners

These are **production FDD rules** in the SQL registry (also pandas cookbook twins). They feed fault hours, plant/VAV health matrices, and FDD Plots — not the Overview Z-score table.

Tune in **Lab** (A–Z rule menu). Sliders write `session_config` / rule params; **Update this rule** then re-run so Reports / FDD Plots refetch (`RULES_UPDATED`). Units follow the Lab unit system (°F canonical in SQL; metric convert at query).

| Rule | Detects | Primary Lab tuners |
|------|---------|-------------------|
| **SV-RANGE** | Sample outside physical hard range (temp / RH / duct static catalogs) | `range_scale_temperature`, `range_scale_humidity`, `range_scale_pressure`, `confirm_seconds`, coverage / startup / operational gate |
| **SV-FLATLINE** | Stuck / frozen sensor (Δ ≤ tol over window) | `flatline_tol`, `flatline_hours`, `confirm_seconds`, gates |
| **SV-SPIKE** | One-sample jump beyond type limit | `spike_scale`, `spike_scale_temperature`, `spike_scale_humidity`, `spike_scale_pressure`, `confirm_seconds` |
| **SV-STALE** | **All** modeled analogs flat over window (feed likely dead) | `stale_hours`, `stale_tol`, `confirm_seconds` |
| **SV-RATE** (alias **SV-SLEW**) | Sustained implausible rate (°F/h-class) vs span / gap | `sensor_span`, `max_gap_hours`, steady fault rate, `confirm_seconds` |

Shared gate knobs on most sweeps: `minimum_active_coverage_pct`, `startup_delay_min`, `require_operational_gate`, `confirm_seconds` (confirm = consecutive seconds before a fault sticks).

Full equations + copy-paste SQL stubs: [DataFusion SQL cookbook → Sensor validation]({{ site.baseurl }}/rules/cookbook/datafusion-sql-cookbook.html#sensor-validation-sweep). Catalog metadata: [P0 rule catalog]({{ site.baseurl }}/rules/cookbook/p0-rule-catalog.html).

---

## 3. Control hunting — `PID-HUNT-1`

| | |
|--|--|
| **Detects** | Rolling lookback where a 0–100% actuator (damper / valve / fan cmd) shows large total variation **and** span |
| **Lab tuners** | `window_hours` (default 1 h), `change_deadband_pct`, `minimum_span_pct`, `total_variation_fault_pct`, plus shared gates / `confirm_seconds` |
| **Cookbook** | [PID-HUNT-1]({{ site.baseurl }}/rules/cookbook/datafusion-sql-cookbook.html#pid-hunt-1--suspected-control-output-hunting) |

Distinct from `SV-SPIKE` / `SV-RATE` (sensor path) and from ASHRAE FC4 hunting where that FC rule is also enabled.

---

## 4. Weather spike — `WX-1`

| | |
|--|--|
| **Detects** | Outdoor-air temperature sample-to-sample jump |
| **Lab tuners** | `spike_limit` (°F, default 16), `confirm_seconds` |
| **Kind** | `weather` equipment / site OAT role |

Related to spike screening but scoped to OAT on weather equipment — not the Overview rolling Z-score table.

---

## 5. How the pieces fit

```text
Package map (Haystack → SQL roles)
        │
        ▼
 Historian Parquet
        │
        ├── Overview POST /api/analytics/sql-anomaly     ← statistical screen
        │         (window_rows, z_threshold, method)
        │
        └── POST /api/fdd/run  (registry SV-*, PID-HUNT-1, WX-1, …)
                  ↑
                  Lab sliders / session_config / confirm_min
```

**Health matrices** on Overview use registry `SV-*` / hunting flags when present; a clean sensor matrix (`rows: []` on `/api/analytics/sensor-faults`) means no `SV-*` faults in window — it does **not** mean the Z-score table is empty.

---

## 6. Ops notes

- Prefer **disable** Overview SQL anomaly on OT-heavy Railway hubs (`OPENFDD_SQL_ANOMALY_SCREENING=0`) if the scan contends with large ACME historians; keep Lab `SV-*` for durable faults.
- Synthetic-59 includes dedicated equipment cases for flatline / range / rate / spike / stale / PID hunt — use those soaks before trusting Lab defaults on a live site.
- Pandas oracle twins live under [Pandas cookbook → Sensor validation]({{ site.baseurl }}/rules/cookbook/pandas-cookbook.html#sensor-validation-sweep) for offline notebooks (`pip install "open-fdd[oracle]"`).
