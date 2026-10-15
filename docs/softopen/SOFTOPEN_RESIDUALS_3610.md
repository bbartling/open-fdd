# Soft-OPEN residuals snapshot — 3.6.10

Soft-OPEN ≠ FQ.

| Area | Soft-OPEN state |
| --- | --- |
| R4 lean plots | `GET /api/fdd/plots-by-rule` + `lean_budget` on Timescale `/api/fdd/plot` |
| R8e/R8d AFDD equip | Chunked AFDD equipment list from Timescale `equipment` (type-first) |
| Analytics pack | Through fuel/anomaly/MV/rcx-coverage (`3.6.9+`) |
| Volume Deletes | Owner UI BLOCKED |
| Grok ART | NOT_AVAILABLE until SUMMARY/MATRIX |

Locks: Rust · Timescale only · `/tmp` worktrees · no backups · Soft-OPEN ≠ FQ.
