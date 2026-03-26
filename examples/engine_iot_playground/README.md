# Engine-only FDD playground (Open-FDD YAML + pandas)

Small **in-repo** demo for teams that already have **data collection** and **modeling** (warehouse, lake, Brick elsewhere) and only want the **same YAML rule format** as Open-FDD, evaluated on **pandas** `DataFrame`s.

## What this is not

- Not a replacement for **`./scripts/bootstrap.sh --mode engine`** (that starts **Docker**: Postgres + `fdd-loop` + weather worker — see Open-FDD `docs/howto/engine_only_iot.md`).
- Not published to PyPI by itself — it uses the **`open-fdd`** Python package (engine lives in `open_fdd.engine`).

## Install — yes, you can `pip install` locally or from PyPI

**What matches your terminal output** (`run_demo.py` working) is the **Python library** — not the Docker stack.

| How | Command | What you get |
|-----|---------|----------------|
| **Editable (dev)** | `cd /path/to/open-fdd && pip install -e .` | Same code as git; best while hacking rules/engine. |
| **PyPI — main package** | `pip install open-fdd` | **`open_fdd.engine`** (`RuleRunner`, same YAML features). Core deps: **pandas**, **PyYAML**. |
| **PyPI — alias package** | `pip install openfdd-engine` | Re-exports `RuleRunner`, `load_rule`, …; depends on **`open-fdd`** underneath. |

After any of the above, `python run_demo.py` from this folder works.

**What is *not* on PyPI:** **`./scripts/bootstrap.sh --mode engine`**. That is **Docker Compose** in the repo (`db` + `fdd-loop` + `weather-scraper`). You get it with **`git clone`** + bootstrap, not `pip install`. The **logic** those services use for rules is the same **`open_fdd`** engine you can install from PyPI for **batch/stream pandas** workflows.

See Open-FDD [engine_only_iot](https://github.com/bbartling/open-fdd/blob/develop/docs/howto/engine_only_iot.md) for the split: **Docker engine mode** vs **library-only**.

## Run the demo

```bash
cd /path/to/open-fdd/examples/engine_iot_playground
source /path/to/open-fdd/.venv/bin/activate   # or any venv where open-fdd is installed
python run_demo.py
```

By default, `run_demo.py` runs on `data/RTU11.csv` with the `rtu11` mapping preset. You should also be able to point it at any other CSV with:

```bash
python run_demo.py --csv /path/to/your.csv --timestamp-col Timestamp --timestamp-format "%d-%b-%y %I:%M:%S %p EST" --preset rtu11
```

## Your IoT pipeline shape

1. **Ingest** — MQTT / historian / Spark → tabular store.
2. **Align columns** — names must match **rule `inputs.*.column`** (or pass **`column_map`** from your own Brick/alias table — same as platform `RuleRunner`).
3. **Run** — `RuleRunner("rules").run(df, timestamp_col="timestamp", skip_missing_columns=True)`.
4. **Downstream** — write flags back to alarms, Kafka, ticketing, etc.

Rule authoring: [expression rule cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook) (same files work here).

## Files

| Path | Purpose |
|------|---------|
| `rules/*.yaml` | Open-FDD-compatible rule configs (subset of platform features). |
| `data/RTU11.csv` | Real RTU sample used in current tutorial flow. |
| `run_demo.py` | CLI demo: load CSV -> map columns -> `RuleRunner` -> fault counts. |
| `RTU11_engine_tutorial.ipynb` | Step-by-step notebook with hourly/monthly fault analytics. |
