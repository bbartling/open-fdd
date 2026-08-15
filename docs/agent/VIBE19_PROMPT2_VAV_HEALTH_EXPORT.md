# Prompt 2 — vibe_code_apps_19 (Windows Cursor)

Copy this whole file into the **Windows Cursor** session that owns
`py-bacnet-stacks-playground` / `vibe_code_apps_19`. Do **not** run this on
bensbench. bensbench only `docker pull ghcr.io/bbartling/vibe19`.

## Goal

Pin the OpenFDD **PyPI** analytics oracle and **export** the same CSVs the
OpenFDD dump-vs-dump scripts already compare. Do **not** reimplement VAV health,
mech OAT bins, or motor hours in Streamlit.

PyPI is live: `open-fdd==4.4.1` (GHA Trusted Publishing, tag `open-fdd-v4.4.1`).

## Pin

In `vibe_code_apps_19` requirements / Docker image:

```text
open-fdd[reporting]==4.4.1
```

Smoke after install:

```python
import open_fdd
from open_fdd.analytics import dump_tables, vav_health_matrix, mech_cooling_oat_bins
assert open_fdd.__version__ == "4.4.1"
assert callable(dump_tables) and callable(vav_health_matrix)
```

## Diagnostic WattLab dump (required files)

The 4.4.0 image imported `vav_health_matrix_v1` but the **diagnostic dump did
not write** `vav_health_matrix.csv`. Fix export only.

Call pandas (do not fork):

```python
from open_fdd.analytics import dump_tables

dump_tables(
    out_dir,  # same folder as MANIFEST / fdd_findings.csv
    frames=frames,
    role_map=role_map,
    rule_results=findings_df,  # so broken_box is not always ?/3
    weather=weather,
    building_id=building_id,
)
```

Must appear in the diagnostic Engineering Bundle + `MANIFEST.json`:

- `vav_health_matrix.csv`
- `mech_cooling_oat_bins.csv`
- `motor_hours.csv`
- `motor_weekly.csv`

Overview matrix is presentation. Do not skip the CSV because the UI already shows a table.

## Rebuild and publish

Rebuild `ghcr.io/bbartling/vibe19` on Windows (or that CI). Tag `:latest` / `:develop` as you already do.

bensbench will then:

```bash
docker pull ghcr.io/bbartling/vibe19:latest
```

## Out of scope

- Do not reimplement FDD rules (call `open_fdd.rules`).
- Do not port Rust-only sensor-stats/diurnal into pandas.
- Do not edit `bbartling/open-fdd` from the playground machine for this prompt.
