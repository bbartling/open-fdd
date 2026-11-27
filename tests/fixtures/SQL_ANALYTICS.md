# SQL analytics hook fixtures

Generate `sql_analytics_cases.json` with:

```sh
python scripts/nf/build_sql_analytics_fixtures.py
python scripts/nf/build_sql_analytics_fixtures.py --check
```

The generator calls the repository's pandas analytics functions, never SQL or
JavaScript. Inputs and expected answers are deterministic synthetic SI data.
Tests replay each case and compare the supported SQL answers on SQLite/DuckDB.

Each case has an `id`, pandas `tool`, equipment `frames`, identity `role_map`,
optional `options` / `web_weather`, and an `expected` answer. Each frame carries
an explicit `equipment_type` and `rows` with integer UTC epoch `ts_ms` plus
canonical role names. Null values represent missing observations. Boolean proof
and cooling mode are 0/1, commands/dampers are percent 0–100, temperatures are °C,
temperature differences are Δ°C, and durations are hours. Legacy `_f` output
names are preserved API names; their values are SI, not Fahrenheit.

| Case | Contract exercised |
| --- | --- |
| runtime-dst-week-gap-percent-command | A 167-hour local DST week, supplied week boundaries and occupied intervals, status priority, a >1-hour unknown gap, percent pump command |
| cooling-individual-percent-and-heat-pump-mode | Individual devices only, percent compressor command, OR'ed RTU stages, heat-pump compressor gated by cooling mode |
| economizer-percent-damper-mixed_air_temperature-holes | Percent damper feedback and missing MAT samples |
| economizer-missing-mixed_air_temperature | Missing role produces an explicit skipped reason |
| web-weather-outage | Bounded backward as-of join leaves outage samples unpaired |
| web-weather-empty | Zero assessed pairs, null statistics rather than a fabricated zero error |

`expected` tables have `columns` and `rows`; weekly timestamps are also UTC epoch
milliseconds. Week labels retain the supplied local timezone's date. Economizer
answers contain `metrics` and `skipped`. Weather answers are keyed by equipment.
Raw weather SQL emits no row when there are zero pairs; hook consumers must
normalize that absence to the fixture's `n=0` / null-statistics contract.

Use `pytest tests/test_sql_analytics_fixtures.py -q` for generator freshness,
missing-data/DST assertions and pandas-to-SQL checks. This fixture is a hook-test
contract, not a live-site export. Do not edit generated JSON by hand.
