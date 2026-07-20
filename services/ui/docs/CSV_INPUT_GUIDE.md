# CSV input guide

## BUILDING_100 tree (default)

Set in `.env`:

```text
HVAC_DATA_ROOT=C:\path\to\hvac_systems_CLEANED
HVAC_BUILDING=BUILDING_100
HVAC_WEATHER_SUBDIR=weather
```

Expected layout:

```text
{HVAC_DATA_ROOT}/
  weather/history_wide.csv
  BUILDING_100/manifest.json
  BUILDING_100/AHU_1/history_wide.csv
  BUILDING_100/AHU_1/columns.csv
  BUILDING_100/VAV/VAV_7/...
```

## Upload CSV

1. Sidebar → **Upload CSV**
2. App detects `timestamp_utc` (or similar) column
3. Assign equipment ID
4. Map roles in **Role Mapping** tab

## Local folder

Point sidebar at any folder containing `history_wide.csv` files (recursive scan).

## columns.csv

Optional sidecar with `column,point_role` — used to suggest roles.
