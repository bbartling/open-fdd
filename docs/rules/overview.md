---
title: Overview
parent: Fault rules for HVAC
nav_order: 1
---

# Fault rules

Fault rules are YAML-defined checks run against time-series DataFrames. Each rule produces a boolean fault flag. **Open-FDD is 100% Brick-model driven:** rule inputs refer only to Brick classes; column mapping comes from the Brick TTL via SPARQL and [Brick external timeseries references](https://docs.brickschema.org/metadata/external-representations.html#timeseries) ([timeseries storage](https://docs.brickschema.org/metadata/timeseries-storage.html)), which Open-FDD embraces at the heart of FDD.

---

## Where rules live: config path and how to manage them

**Single directory:** All FDD rule YAML files live in one directory configured as **`rules_dir`** in platform config (RDF: `ofdd:rulesDir`, e.g. `"stack/rules"`). The FDD loop loads from this path every run; the rules API (list, upload, download, delete) uses the same path. **You still need `rules_dir` in config** — it defines where files are stored. The frontend does not replace it; it lets you manage the files *in* that directory.

**Two ways to manage rules:**

| Method | Use case |
|--------|----------|
| **React frontend (Faults page)** | Upload new YAML, download existing files, delete files, and **Sync definitions** so the fault_definitions table updates without waiting for the next FDD run. Preferred when you have UI access. |
| **Files on disk** | Edit or add files directly under the configured path (e.g. `stack/rules/` on the host or in the container). Same outcome: next FDD run (or **Sync definitions** from the UI) picks them up. |

Config: `rules_dir: "stack/rules"` (GET/PUT `/config` or `OFDD_RULES_DIR` at bootstrap). If that path does not exist, the loop falls back to `stack/rules`. Default rules ship in `stack/rules/` (e.g. `sensor_bounds.yaml`, `sensor_flatline.yaml`). See the [Expression Rule Cookbook](../expression_rule_cookbook) to add or adapt rules. For how YAML becomes pandas operations and how telemetry is pivoted into a DataFrame, see [YAML rules → Pandas (under the hood)](pandas_yaml_dataframes).

**Reference rule library (not loaded by default):** Additional AHU, chiller, heat-pump, and weather YAML examples used for lab automation and docs live under **`openclaw/bench/rules_reference/`** in the repo. See the [Test bench rule catalog](test_bench_rule_catalog) for a table of every file with GitHub links.

---

## Hot reload (edit → run → view)

Open-FDD is **AFDD** (Automated Fault Detection and Diagnostics). The project **supports hot reloading of YAML rule files** so the AFDD maintainer can tune faults without restarting. Rule YAML contains fault logic and **params** (thresholds, tolerances, windows); the FDD loop loads from `rules_dir` every run — no restart.

**Fault definitions:** Each FDD run syncs the loaded rules into the `fault_definitions` table (fault_id, name, category, equipment_types). When you add or edit a rule (via frontend upload or by editing a file in `rules_dir`), the next run updates the DB and the Faults UI reflects the change. From the frontend you can also click **Sync definitions** to update the definitions table immediately.

1. **Add or edit** rules: use the Faults page (upload/paste YAML, or choose file) or edit files in `stack/rules/*.yaml`. Change `params` (e.g. `tolerance`, `rolling_window`) to tune sensitivity.
2. **Run** FDD: wait for the next scheduled run (per `rule_interval_hours` and `lookback_days` in [platform config](../configuration)), or trigger with `touch config/.run_fdd_now` or `POST /run-fdd` (see [Appendix: API Reference](../appendix/api_reference)). Or use **Sync definitions** in the UI to only refresh the definitions table.
3. **View** fault results in the React Faults/Plots views or in Grafana (see [Grafana SQL cookbook](../howto/grafana_cookbook)). Every run reloads all rules from disk — hot reload.

---

## Rule types

| Type | Purpose |
|------|---------|
| `bounds` | Value outside `[low, high]` |
| `flatline` | Rolling spread < tolerance (stuck sensor) |
| `hunting` | Excessive state changes (PID hunting) |
| `expression` | Custom pandas/numpy expression |
| `oa_fraction` | OA fraction vs design airflow error |
| `erv_efficiency` | ERV effectiveness out of range |

---

## YAML structure

Inputs use **Brick class names** only; the Brick TTL (SPARQL) resolves each to a DataFrame column via external timeseries references. No `column` in YAML.

```yaml
name: sensor_bounds
type: bounds
flag: bad_sensor
inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
params:
  low: 40
  high: 90
  rolling_window: 6   # optional: require N consecutive True samples before flagging
```

**Per-rule rolling window:** Set `params.rolling_window` (e.g. `6`) in a rule to require that many consecutive True samples before the fault is flagged. Omit for “flag on any True.” See `sensor_flatline.yaml`, `weather_temp_stuck.yaml`.

---

## Input resolution (100% Brick)

- **Brick TTL:** Each rule input declares a Brick class (e.g. `brick: Supply_Air_Temperature_Sensor`). The engine resolves Brick points via SPARQL to their [external timeseries reference](https://docs.brickschema.org/metadata/external-representations.html#timeseries) (`ref:TimeseriesReference` / `ref:hasTimeseriesId`), yielding the DataFrame column name. See [Brick timeseries storage](https://docs.brickschema.org/metadata/timeseries-storage.html).
- **Column map:** Built from the Brick model (e.g. `rdfs:label` or external_id) → column names; no `column` in rule YAML.

---

## Running rules

- **Platform:** FDD loop loads rules from `rules_dir` (default `stack/rules`) each run; edit YAML and trigger a run to see changes in Grafana.
- **Standalone:** `RuleRunner(rules_path=...)` or `RuleRunner(rules=[...])`; call `run(df, ...)`.

---

## Engineering metadata (223P-style) and energy-style analytics

FDD rules consume **time-series columns** built from the Brick graph (`ref:TimeseriesReference` + `ofdd:mapsToRuleInput`). **Engineering** data (design CFM, cooling tons, heating MBH, `s223:*` connection topology) lives on **equipment** in the DB and in the **same TTL** after import.

That split is intentional: the RuleRunner stays fast and pandas-centric. **Downstream**, you can combine:

- **Fault results** (which equipment, which fault, when), and
- **SPARQL** (or export TTL) for **rated capacity** and **topology** on that equipment, and
- **SQL** on `timeseries_readings` for duty estimates over the fault window

…to approximate **energy penalties** or rank impact (see `examples/223P_engineering/energy_penalty_sandbox.md` and [Data model engineering (Brick + 223P MVP)](../howto/data_model_engineering)).

---

## Cookbook

See [Expression Rule Cookbook](../expression_rule_cookbook) for AHU, chiller, weather, and advanced recipes.
