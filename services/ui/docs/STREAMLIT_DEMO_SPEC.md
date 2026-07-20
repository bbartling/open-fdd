# Streamlit FDD demo spec

## Purpose

Educational **pandas + Streamlit** lab for BUILDING_100-style CSV historian data. Tunable fault thresholds, readable rules, engineer notes on charts.

**Not** Open-FDD. Production Rust/DataFusion engine: `C:\Users\ben\Documents\open-fdd`.

## Screens (tabs)

1. **Overview** — data source, equipment count, date range, poll interval, missing roles
2. **Data Preview** — dataframe head, columns, timestamp health
3. **Role Mapping** — assign semantic roles, save YAML
4. **Rule Tuning** — sliders from `configs/rule_defaults.yaml`, run rules
5. **Fault Results** — summary table, top faulted equipment
6. **Trends** — point plots with optional fault overlay + engineer notes
7. **Export** — CSV summary, debug CSV, Markdown/HTML report

## Rules (demo subset)

| ID | Module | Notes |
| --- | --- | --- |
| FAN-RUNTIME | fan_rules | Fan on hours |
| VAV-1 | vav_rules | Zone comfort band |
| AVG-ZONE-TEMP | vav_rules | Analytics |
| ZONE-COMFORT-PCT | vav_rules | Analytics |
| SAT-HIGH | ahu_rules | FC13-style |
| ECON-2 | economizer_rules | Unfavorable economizing |
| ECON-1 | economizer_rules | Stuck closed |
| OAT-METEO | economizer_rules | Needs weather CSV |
| FC2-MAT-LOW | ahu_rules | Mixed air low |

## Data inputs

See `CSV_INPUT_GUIDE.md`, `SQL_INPUT_GUIDE.md`.

## Performance

- `st.cache_data` on loads
- Vectorized pandas masks
- Load selected equipment when possible
