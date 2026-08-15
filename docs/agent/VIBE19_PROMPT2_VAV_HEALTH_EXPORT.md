# Prompt 2 — CLOSED (playground PR #92)

Do **not** run further Windows work for VAV health CSV export. bensbench only `docker pull ghcr.io/bbartling/vibe19:latest`.

## Closeout (Windows Cursor reported)

| Item | Value |
| --- | --- |
| Merge | `4b71061666d1c34c9c93b3c66fa08e043ae856ae` |
| PR | [#92](https://github.com/bbartling/py-bacnet-stacks-playground/pull/92) into `develop` |
| Pin | `open-fdd[reporting]==4.4.1` |
| Catalog hash | `2e684dbb8f3188f06942c3cb0155aef4149713e7244b9f7733262f182465cba9` |
| GHCR | `:latest` / `:develop` rebuilt green |

Diagnostic and forensic dumps call `open_fdd.analytics.dump_tables`. Engineering Bundle + `MANIFEST.json` include `vav_health_matrix.csv`, `mech_cooling_oat_bins.csv`, `motor_hours.csv`, `motor_weekly.csv`.

## bensbench verification 2026-08-15

- Image digest `sha256:101126abbe4d0affe4ffac6a8cf03bd5a1f31fe8e7161e6eb354910f32760f07`
- `docker exec vibe19` → `open_fdd.__version__ == 4.4.1`, `dump_tables` importable
- Oracle dump wrote all four analytics CSVs
- Synthetic-59 target pairs **59/59** on vibe19

No new Windows prompt unless a later dump is missing those files again.
