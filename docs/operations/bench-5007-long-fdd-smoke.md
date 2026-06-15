# Bench 5007 long FDD smoke

Validates **data-source-agnostic FDD**, **PyArrow vs DataFusion SQL equivalence**, and the **fault confirmation window** on BACnet 5007 + Niagara bench9065 (site `demo`).

**Read-only:** polls devices; only Open-FDD evaluation thresholds change. Never prints credentials.

## Commands

| Mode | Command |
|------|---------|
| CI synthetic | `python scripts/smoke_bench_5007_long_fdd.py --synthetic` |
| Dev dry-run (~15 min) | `python scripts/smoke_bench_5007_long_fdd.py --dry-run` |
| Default (2 h) | `./scripts/smoke_bench_5007_long_fdd.sh` |
| Overnight (12 h) | `python scripts/smoke_bench_5007_long_fdd.py --overnight` |

## Key environment

| Variable | Default |
|----------|---------|
| `OPENFDD_BASE_URL` | `http://127.0.0.1:8765` |
| `OPENFDD_SMOKE_DURATION_MINUTES` | `120` (720 if `OPENFDD_SMOKE_OVERNIGHT=true`) |
| `OPENFDD_SMOKE_POLL_SECONDS` | `60` |
| `OPENFDD_SMOKE_BASELINE_MINUTES` | `20` |
| `OPENFDD_SMOKE_CONFIRMATION_ROWS` | `10` |
| `OPENFDD_SMOKE_CONFIRMATION_MINUTES` | `10` |
| `OPENFDD_SMOKE_PRIMARY_SEMANTIC` | `duct-t` |
| `OPENFDD_SMOKE_FORCED_THRESHOLD_F` | `80.0` |

## Fault confirmation window

At 1-minute polling, `min_true_rows = 10` means the raw condition must stay true for about **10 minutes** before a **confirmed fault** is reported. See [fault-confirmation.md](../rule-cookbook/fault-confirmation.md).

## Artifacts

- `workspace/reports/bench_5007_long_fdd_<timestamp>.md`
- `workspace/reports/bench_5007_long_fdd_<timestamp>.json`
- `workspace/reports/bench_5007_long_fdd_<timestamp>_events.csv`

## Pass / fail

| Verdict | Meaning |
|---------|---------|
| **PASS** | All checks passed; confirmation fully vectorized (not expected today) |
| **WARN** | Core FDD uses `pyarrow_compute` / `datafusion_sql`; confirmation engine is `python_loop_over_arrow_mask` (known tech debt) |
| **FAIL** | `python_list` core crunching, early confirmed fault, backend mismatch, missing data, or secrets in output |

Live mode uses `POST /api/bench/long-fdd/evaluate` (validation/smoke only).

## Related

- [Dual-source smoke](./bench-5007-dual-source-smoke.md)
- [Fault confirmation](../rule-cookbook/fault-confirmation.md)
