# Stage 4 — Parity status (BUILDING_100)

**Status: COMPLETE @ 0.5h tolerance** (2026-07-09)

- **368 pass / 0 fail / 11 skipped**
- 19/19 SQL rules execute
- Material mismatch list empty

## How it was fixed

1. **OAT-METEO + ECON-4** — LAG-based confirm-streak CTE (not join/denominator)
2. **All remaining FC/VAV/ECON rules** — same streak CTE applied bulk
3. **ECON-2** — registry `confirm_seconds` aligned to cookbook (300, not 900)

## Valid skips (unchanged)

- FC7 / ECON-5 — missing historian columns on BUILDING_100
- FAN-RUNTIME on plant — no fan points
- VAV_25A — missing zone_t

## Next (Stage 5+)

- SQL tuning completeness (registry `parameters:` for all rules)
- Per-request Rust preview from dashboard
- Merge policy: parity proven — focus shifts to tuning UX and pandas reduction plan
