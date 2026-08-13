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
