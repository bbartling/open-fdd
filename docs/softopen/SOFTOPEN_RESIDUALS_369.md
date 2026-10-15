# Soft-OPEN residuals snapshot — 3.6.9

Soft-OPEN ≠ FQ.

| Area | Soft-OPEN state |
| --- | --- |
| Analytics pack | Bodies through fuel / sql-anomaly / mv-change-point / rcx-preset-coverage (`3.6.8+`) |
| R6 adapters | 12/12 Soft-OPEN dispositions + harness |
| R8c successor | `FILES.sha256` + original warehouse hash preserved |
| R8e AFDD | Scheduled cycles + status use Timescale `max(ts)` (scope-aware); catch-up FQ later |
| Fuel POST | Timescale `fuel_daily` when `building_id` set; campus EUI stays rust-fuel |
| Volume Deletes | Owner UI BLOCKED |
| Grok ART | NOT_AVAILABLE until SUMMARY/MATRIX returns |

Locks: Rust · Timescale only · `/tmp` worktrees · no backups · Soft-OPEN ≠ FQ.
