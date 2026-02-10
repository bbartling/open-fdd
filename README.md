# open-fdd

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

**Config-driven FDD** for HVAC — YAML fault rules, pandas DataFrames, and optional Brick model–driven column mapping.

Pandas is an excellent choice for high-performance, tabular computing and rule-based fault detection. If you know Python and love pandas, you'll feel right at home — especially if you're a visual or spatial thinker (or both) who likes to see data in tables and trace logic through expressions. pandas provides fast, spreadsheet-like DataFrames for cleaning, wrangling, analyzing, and computing on time-series data using simple, Excel-style operations at scale; it was created in 2008 by Wes McKinney while working in finance to handle large time-series datasets more efficiently and later became a core project in the scientific Python ecosystem under the NumFOCUS foundation.


> open-fdd is under construction with daily updates. Stay tuned for version 2.0! Be sure to check out the new online docs!


## Quick Start

Map BRICK class names to your raw BAS column headers (e.g. `SAT (°F)`, `SF Spd Cmd (%)`), then run rules:

```python
import pandas as pd
from pathlib import Path
from open_fdd import RuleRunner
from open_fdd.engine import load_rule
from open_fdd.reports import summarize_fault, print_summary

# Raw BAS point names (as exported from your BMS)
df = pd.DataFrame({
    "timestamp": [
        "2023-01-01 00:00", "2023-01-01 00:15", "2023-01-01 00:30", "2023-01-01 00:45",
    ],
    "SA Static Press (inH₂O)": [0.4, 0.4, 0.2, 0.2],
    "SA Static Press SP (inH₂O)": [0.5, 0.5, 0.5, 0.5],
    "SF Spd Cmd (%)": [0.95, 0.95, 0.95, 0.95],
})

# BRICK class -> raw BAS column name
column_map = {
    "Supply_Air_Static_Pressure_Sensor": "SA Static Press (inH₂O)",
    "Supply_Air_Static_Pressure_Setpoint": "SA Static Press SP (inH₂O)",
    "Supply_Fan_Speed_Command": "SF Spd Cmd (%)",
}

rules_dir = Path("open_fdd/rules")
runner = RuleRunner(rules=[load_rule(rules_dir / "ahu_rule_a.yaml")])
result = runner.run(
    df,
    timestamp_col="timestamp",
    column_map=column_map,
    rolling_window=3,  # fault only if true for 3+ consecutive samples
)
summary = summarize_fault(
    result,
    "rule_a_flag",
    timestamp_col="timestamp",
    motor_col=column_map["Supply_Fan_Speed_Command"],
)
print_summary(summary, "Rule A (duct static)")
```

## Rule expression example (Rule G)

Rules use BRICK class names in `inputs`; `column_map` maps them to your raw BAS columns:

```yaml
name: oat_too_high_free_cooling
type: expression
flag: rule_g_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: OAT (°F)
  sat_setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: SAT SP (°F)
  economizer_sig:
    brick: Damper_Position_Command
    column: OA Damper Cmd (%)
  cooling_sig:
    brick: Valve_Command
    column: Clg Vlv Cmd (%)

params:
  outdoor_err_thres: 1.0
  delta_t_supply_fan: 0.5
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (oat - outdoor_err_thres > sat_setpoint - delta_t_supply_fan + supply_err_thres) & (economizer_sig > ahu_min_oa_dpr) & (cooling_sig < 0.1)
```

```python
# column_map: BRICK class -> raw BAS column (as exported from BMS)
column_map = {
    "Outside_Air_Temperature_Sensor": "OAT (°F)",
    "Supply_Air_Temperature_Setpoint": "SAT SP (°F)",
    "Damper_Position_Command": "OA Damper Cmd (%)",
    "Valve_Command": "Clg Vlv Cmd (%)",
}
```

With Brick TTL, use `resolve_from_ttl("model.ttl")` instead of a manual `column_map`.

## Getting Started

Please see the online docs for setup and running HVAC fault checks with pandas.

[📖 Docs](https://bbartling.github.io/open-fdd/)


## Dependencies

[pandas](https://github.com/pandas-dev/pandas) · [PyYAML](https://github.com/yaml/pyyaml) · optional: [matplotlib](https://github.com/matplotlib/matplotlib) (viz), [rdflib](https://github.com/RDFLib/rdflib) (Brick TTL)


## Platform stack & monitoring

**Quick start:** From repo root run `./scripts/bootstrap.sh` to start the full stack (TimescaleDB, Grafana, diy-bacnet-server, bacnet-scraper, weather-scraper, API). Use `./scripts/bootstrap.sh --minimal` for DB + Grafana only. **Prerequisite:** [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server) as a sibling directory for BACnet ingestion.

| Step | Command / URL |
|------|----------------|
| Start stack | `./scripts/bootstrap.sh` |
| Verify | `./scripts/bootstrap.sh --verify` |
| Grafana | http://localhost:3000 (admin/admin) → Open-FDD folder |
| API docs | http://localhost:8000/docs |
| BACnet Swagger | http://localhost:8080/docs (when diy-bacnet-server is running) |

- **BACnet:** bacnet-scraper polls points every 5 min (configurable via `OFDD_BACNET_SCRAPE_INTERVAL_MIN`); requires diy-bacnet-server and `config/bacnet_discovered.csv` (or `OFDD_BACNET_SCRAPE_CSV`).
- **Weather:** weather-scraper fetches Open-Meteo once per day (configurable via `OFDD_OPEN_METEO_INTERVAL_HOURS`). Set `OFDD_OPEN_METEO_LATITUDE`, `OFDD_OPEN_METEO_LONGITUDE` (and optional `OFDD_OPEN_METEO_TIMEZONE`, `OFDD_OPEN_METEO_SITE_ID`) for your site; disable with `OFDD_OPEN_METEO_ENABLED=false`.
- **Grafana datasource:** If the TimescaleDB datasource fails, add it manually: Host `db`, Port `5432`, Database `openfdd`, User/Password `postgres`, **SSL: Disable**. See [MONOREPO_PLAN.md](MONOREPO_PLAN.md) for full datasource and dashboard notes.

Full setup (discovery, CSV trim, env vars, troubleshooting): **[MONOREPO_PLAN.md](MONOREPO_PLAN.md)**.

**Check resource usage** (useful on edge devices):

```bash
free -h && uptime                              # RAM, swap, load average
ps aux --sort=-%mem | head -10                  # top memory processes
ps aux --sort=-%cpu | head -10                  # top CPU processes
docker stats --no-stream                        # container CPU/memory
docker compose -f platform/docker-compose.yml logs -f bacnet-scraper   # BACnet scrape activity
docker compose -f platform/docker-compose.yml logs -f openfdd_weather_scraper   # Open-Meteo weather fetch
```

**Signs of overload:** high load average (> cores), swap in use, `docker stats` showing sustained high CPU/memory. See `MONOREPO_PLAN.md` for more.

**After machine seizure or reboot:** TimescaleDB and Grafana may have exited. Restart the full stack:

```bash
docker compose -f platform/docker-compose.yml up -d
```

**"could not translate host name 'db'"** — The bacnet-scraper cannot reach TimescaleDB. The db container is down. Start it with `docker compose -f platform/docker-compose.yml up -d db grafana`.

**405 Method Not Allowed** on BACnet RPC — The scraper image may be outdated. Rebuild and restart:

```bash
docker compose -f platform/docker-compose.yml build bacnet-scraper
docker compose -f platform/docker-compose.yml up -d bacnet-scraper
```

**Grafana datasource error** — If the TimescaleDB datasource fails, add it manually: Connections → Data sources → Add → PostgreSQL. Host: `db`, Port: `5432`, Database: `openfdd`, User: `postgres`, Password: `postgres`, SSL: Disable. Save & test.

## Contributing

Open FDD is under construction but will be looking for testers and contributors soon, especially to complete a future open-source fault rule cookbook.

## License

MIT
