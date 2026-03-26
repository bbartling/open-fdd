---
title: Examples
nav_order: 12
nav_exclude: true
---

# Examples

Scripts and sample data for **open-fdd** tutorials.

## Contents

| File | Description |
|------|-------------|
| `check_faults_ahu7_flatline.py` | Flatline (stuck sensor) detection |
| `check_faults_ahu7_bounds.py` | Bounds (out-of-range) sensor check |
| `my_rules/sensor_flatline.yaml` | Flatline rule config (your rules) |
| `my_rules/sensor_bounds.yaml` | Bounds rule config (your rules) |
| `data_model.ttl` | Data model TTL (Brick + optional BACnet) (optional) |
| `brick_resolver.py` | Resolve column map from TTL |

## Data

The tutorials use `data_ahu7.csv` (~10k rows, AHU7 BAS export). Place it in the `examples/` directory before running the scripts.

## Run

```bash
cd examples
python check_faults_ahu7_flatline.py
python check_faults_ahu7_bounds.py
```

---

## my_rules — Your fault rules

The `examples/my_rules/` folder holds **your** YAML fault rules. Copy it, rename if you like, and customize for your own BAS data.

### Brick-driven workflow

When using `data_model.ttl` and `run_all_rules_brick.py`:

1. **Validate first**: `python examples/validate_data_model.py`
2. **Run faults**: `python examples/run_all_rules_brick.py`

Rules with `equipment_type: [VAV_AHU]` (or `[AHU, VAV_AHU]`) only run when the Brick model declares that equipment type via `ofdd:equipmentType`.

### Rules in my_rules

| Rule | Type | equipment_type |
|------|------|----------------|
| sensor_bounds.yaml | bounds | (all) |
| sensor_flatline.yaml | flatline | (all) |
| ahu_rule_a.yaml | expression | VAV_AHU |
| ahu_fc2.yaml | expression | AHU, VAV_AHU |
| ahu_fc3.yaml | expression | AHU, VAV_AHU |
| ahu_fc4.yaml | hunting | AHU, VAV_AHU |

---

## Cloud export example

Pull fault and timeseries data from the Open-FDD API. Use as a **starting point** for cloud or MSI integration. See [Concepts — Cloud export](concepts/cloud_export.md).

### Run locally

```bash
pip install httpx
python examples/cloud_export.py
python examples/cloud_export.py --site default --days 14
API_BASE=http://your-openfdd:8000 python examples/cloud_export.py
```

### Run in Docker

```bash
docker build -t openfdd-cloud-export -f examples/cloud_export/Dockerfile .
docker run --rm -e API_BASE=http://host.docker.internal:8000 openfdd-cloud-export
```

On Linux use `http://172.17.0.1:8000` or your host IP if host.docker.internal is unavailable.

### What it does

1. **GET /download/faults?format=json** — fault results for MSI/cloud ingestion
2. **GET /download/faults?format=csv** — fault CSV (Excel-friendly)
3. **GET /analytics/motor-runtime** — motor runtime (data-model driven)
4. **GET /download/csv** — timeseries wide-format CSV
5. **GET /analytics/fault-summary** — fault counts by fault_id

Replace the `print()` calls with your cloud integration (Azure IoT Hub, AWS, SkySpark, custom REST, etc.).

---

## Brick Fault Visualization

Run Brick-driven fault detection and **zoom in on fault events** in an IPython notebook.

### Quick start

1. From project root: `jupyter notebook examples/brick_fault_viz/run_and_viz_faults.ipynb`
2. Run all cells
3. Inspect the random fault-event zooms

### What it does

- Runs the same Brick workflow as `run_all_rules_brick.py` (TTL → column map → rules → CSV)
- Extracts **fault events** (contiguous runs of True in each flag column)
- **Randomly samples** events and plots a zoomed time window around each
- Shows signals (SAT, MAT, OAT, RAT, duct static, damper, valves) with fault region shaded

---

## Engine IoT playground

Engine-only CSV + YAML walkthrough inside the repo:

- Folder: `examples/engine_iot_playground/`
- Script: `examples/engine_iot_playground/run_demo.py`
- Notebook: `examples/engine_iot_playground/RTU11_engine_tutorial.ipynb`
- Data/rules: `examples/engine_iot_playground/data/RTU11.csv`, `examples/engine_iot_playground/rules/*.yaml`

Run quickly:

```bash
cd examples/engine_iot_playground
python run_demo.py
```
