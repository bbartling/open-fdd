---
title: SQL anomaly detection
parent: Rule Cookbook
nav_order: 0
permalink: /rules/sql-anomaly-detection/
---

# SQL anomaly detection

The API and SQL processing contract is SI (`metric-c-v2`). Engineer-declared source units are normalized once at ingest. User display preference is applied only in presentation; relative quantities use scale-only conversion. See [unit contract]({{ site.baseurl }}/modeling/units/).


Open-FDD ships **two** anomaly-style layers. Do not conflate them:

| Layer | What it is | Where you see it | Tuners |
|-------|------------|------------------|--------|
| **Overview SQL anomaly screening** | Prior-window z-score event table on mapped sensors | Overview → **Anomaly screening (SQL)** | Request `series` params (not Lab rule sliders) |
| **Registry rules (`SV-*`, `PID-HUNT-1`, `WX-1`)** | Deterministic physics / quality / hunting screens in PostgreSQL SQL | Lab → **SQL FDD Rules** → Run all / FDD Plots · plant health matrices | Lab sliders from [`sql/fdd/registry.yaml`](https://github.com/bbartling/open-fdd/blob/master/sql/fdd/registry.yaml) |

Neither layer is ML or peer-fleet scoring. Peer / self-baseline expansion beyond the Overview screen remains optional follow-on work.

---

## 1. Overview SQL anomaly screening

**Purpose:** Flag individual samples whose value is far from that series’ own recent baseline — useful when a hard range check is still inside limits but one timestamp is not.

**Engine:** Timescale SQL on the product historian (`POST /api/analytics/sql-anomaly`, `query_version: sql-anomaly-event-v1`). The response is an **event table**. Each row is one flagged timestamp. Coverage on the same envelope says how many samples were scored, why a series produced no rows, and whether the table was cut at 2000 events.

**UI:** React Overview section `data-testid="overview-sql-anomaly"`. Window, threshold, and “Rising edges only” are the request. The table lists equipment, role, UTC time, value, baseline, sample standard deviation, |z|, threshold, flag, and whether the row is a rising edge. No Plotly.

**Hub flag:**

| Env | Default | Meaning |
|-----|---------|---------|
| `OPENFDD_SQL_ANOMALY_SCREENING` | **on** when unset | Set `0` / `false` / `off` to skip the scan and return an empty event table |
| Status | — | `GET /api/analytics/sql-anomaly/status` → `{ enabled, mode }` |

### Screened roles

`sat`, `mat`, `rat`, `oa_t`, `web_oa_t`, `zone_t`, `dsp`.

The role is `split_part(openfdd_key, '.', 2)` and must be one of those names. Equipment selection is an exact id list (`= ANY ($4)`). A missing role is not screened.

### Score

The baseline for a sample is the previous `window_rows` numeric values on the same equipment and role. The current sample is not part of its own mean or sample standard deviation. A sample is scored only when that prior window is full and the sample standard deviation is positive.

`|z| = |value − prior mean| / prior sample stddev`. The row is an event when `|z| >= z_threshold`.

`transition_events: false` (Overview default) returns every flagged timestamp. `true` returns rising edges only. `coverage.n_flagged` still counts flagged samples the edge filter omits.

Any `series.method` other than `zscore` returns a warning and no rows. The route does not invent a second score.

### Request tuners (`series` object)

| Key | Type | Default | Notes |
|-----|------|---------|--------|
| `window_rows` | u32 | `24` | Clamped **3–168**. This is the prior-sample count, not a whole-window aggregate. |
| `z_threshold` | f64 | `3.0` | Positive and finite. Values above `1e6` are capped. Non-positive values stay at `3.0`. |
| `method` | string | `"zscore"` | Only `zscore` produces rows. |
| `transition_events` | bool | `false` | `true` keeps rising edges. Coverage still reports every flag. |

**Event columns:** `anomaly_flag` (`ANOMALY`), `avg_val`, `equipment_id`, `method` (`zscore`), `role`, `stddev_val`, `threshold`, `transition`, `ts` (UTC, microsecond RFC3339), `val`, `z_abs`.

**Coverage:** `contract` (`event-table`), `semantics` (`rolling-prior-window-zscore`), the request controls, `truncated`, window bounds, `n_samples`, `n_scored`, `n_flagged`, `n_ok`, `n_returned`, and per-series `reason` (`scored`, `short_history`, `constant_history`, `missing_values`) with `n` and `n_null`. An empty window is a warning and an empty row list. It is not a zero-filled summary.

**Example:**

```bash
curl -sS -X POST "$OPENFDD_API_BASE/api/analytics/sql-anomaly" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "building_id": "<building_id>",
    "query_version": "sql-anomaly-event-v1",
    "series": {
      "window_rows": 48,
      "z_threshold": 2.5,
      "method": "zscore",
      "transition_events": false
    }
  }'
```

There is no Lab slider strip for this analytics path. Tune it from Overview or the API `series` body. After **Update this rule** on registry rules, Overview still refreshes this table on building / refresh token only. SQL text: [`sql_anomaly_zscore.sql`](https://github.com/bbartling/open-fdd/blob/master/sql/analytics/postgres/queries/sql_anomaly_zscore.sql) and [`sql_anomaly_series.sql`](https://github.com/bbartling/open-fdd/blob/master/sql/analytics/postgres/queries/sql_anomaly_series.sql).

---

## 2. Sensor validation rules (`SV-*`) — Lab tuners

These are **production FDD rules** in the SQL registry (also pandas cookbook twins). They feed fault hours, plant/VAV health matrices, and FDD Plots — not the Overview Z-score table.

Tune in **Lab** (A–Z rule menu). Sliders write `session_config` / rule params; **Update this rule** then re-run so Reports / FDD Plots refetch (`RULES_UPDATED`). Rule processing uses SI (`metric-c-v2`); display preference is applied only in the SPA.

| Rule | Detects | Primary Lab tuners |
|------|---------|-------------------|
| **SV-RANGE** | Sample outside physical hard range (temp / RH / duct static catalogs) | `range_scale_temperature`, `range_scale_humidity`, `range_scale_pressure`, `confirm_seconds`, coverage / startup / operational gate |
| **SV-FLATLINE** | Stuck / frozen sensor (Δ ≤ tol over window) | `flatline_tol`, `flatline_hours`, `confirm_seconds`, gates |
| **SV-SPIKE** | One-sample jump beyond type limit | `spike_scale`, `spike_scale_temperature`, `spike_scale_humidity`, `spike_scale_pressure`, `confirm_seconds` |
| **SV-STALE** | **All** modeled analogs flat over window (feed likely dead) | `stale_hours`, `stale_tol`, `confirm_seconds` |
| **SV-RATE** (alias **SV-SLEW**) | Sustained implausible rate (°F/h-class) vs span / gap | `sensor_span`, `max_gap_hours`, steady fault rate, `confirm_seconds` |

Shared gate knobs on most sweeps: `minimum_active_coverage_pct`, `startup_delay_min`, `require_operational_gate`, `confirm_seconds` (confirm = consecutive seconds before a fault sticks).

Full equations + copy-paste SQL stubs: [PostgreSQL SQL cookbook → Sensor validation]({{ site.baseurl }}/rules/cookbook/sql-cookbook.html#sensor-validation-sweep). Catalog metadata: [P0 rule catalog]({{ site.baseurl }}/rules/cookbook/p0-rule-catalog.html).

---

## 3. Control hunting — `PID-HUNT-1`

| | |
|--|--|
| **Detects** | Rolling lookback where a 0–100% actuator (damper / valve / fan cmd) shows large total variation **and** span |
| **Lab tuners** | `window_hours` (default 1 h), `change_deadband_pct`, `minimum_span_pct`, `total_variation_fault_pct`, plus shared gates / `confirm_seconds` |
| **Cookbook** | [PID-HUNT-1]({{ site.baseurl }}/rules/cookbook/sql-cookbook.html#pid-hunt-1--suspected-control-output-hunting) |

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
 Timescale historian
        │
        ├── Overview POST /api/analytics/sql-anomaly     ← event table
        │         (window_rows, z_threshold, transition_events)
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
