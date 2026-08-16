# Building 100 mech cooling OAT bins — OpenFDD fix notes

**Verdict (2026-08-13):** OpenFDD was wrong vs vibe19/pandas (no playground handoff).

| Side | Peak bin | Peak h | Total device-h |
|------|----------|--------|----------------|
| OpenFDD (pre-fix, tip `c8b0302`) | 65–70°F | 289.0 | 1255.5 |
| vibe19 | 70–75°F | ~204.6 | ~1156.5 |

## Root causes

1. **`cooling_on_expr` OR'd status with amps** — amps linger after status off (~+99 h). Match pandas hierarchy: status/cmd first; amps only if no status.
2. **OAT source** — site `AVG(oa_t)` mixed AHU BAS sensors. Prefer `web_oa_t` / `dry_bulb_f` / weather-equipment OAT.

## Product patches (this PR)

- `services/central/src/analytics/historian.rs` — status-before-amps; web/`dry_bulb_f` preference; weather `oa_t` broadcast with site fallback.

## Local package (gitignored workspace)

After tip pull, map weather dry-bulb and re-ingest:

```text
workspace/data/csv_buildings/BUILDING_100/weather/columns.csv
  dry_bulb_f,web_oa_t
```

Then re-upload/re-ingest Building 100 so historian sees `web_oa_t`. Empty `role` for `dry_bulb_f` leaves only BAS `oa_t` on the stack.

**2026-08-14:** Operator wrote `dry_bulb_f,web_oa_t` via `sudo tee`. Re-ingest BUILDING_100 after the stack is on `OPENFDD_IMAGE_TAG=sha-*` (`openfdd_stack_up.sh … --no-pull`) so parquet/historian pick up `web_oa_t`. Spot-check mech OAT bins vs vibe19 after that ingest.

**Soak (bensbench, `OPENFDD_IMAGE_TAG=sha-a13c8b4`, master `a13c8b4`):** `POST /api/analytics/mechanical-cooling` for `BUILDING_100` reports `oat_column=web_oa_t`, `oat_join=site_broadcast_web_by_ts`. Aggregate peak bin **70–75°F / 204.58 h**, total **1156.5** device-h — matches vibe19 in the table above. `POST /api/analytics/vav-health` returns `vav_health_matrix_v1` (43 terminals; `?/3` until FDD results populate broken-box). Catalog `/api/fdd/rules` count **63**.
