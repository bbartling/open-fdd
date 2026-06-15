# Bench 5007 long FDD validation smoke

Long-running validation proving **data-source-agnostic FDD**, **PyArrow vs DataFusion SQL equivalence**, and the **fault confirmation window** on the Benserver dual-source bench (BACnet 5007 + Niagara bench9065).

## Modes

| Mode | Duration | Command |
|------|----------|---------|
| **Synthetic (CI)** | seconds | `python scripts/smoke_bench_5007_long_fdd.py --synthetic` |
| **Developer dry-run** | ~15 min | `python scripts/smoke_bench_5007_long_fdd.py --dry-run` (explicit) |
| **Default validation** | 2 hours | `./scripts/smoke_bench_5007_long_fdd.sh` |
| **Overnight** | 12 hours | `python scripts/smoke_bench_5007_long_fdd.py --overnight` |

## Environment

| Variable | Default |
|----------|---------|
| `OPENFDD_BASE_URL` | `http://127.0.0.1:8765` |
| `OPENFDD_AUTH_ENV` | `workspace/auth.env.local` |
| `OPENFDD_SMOKE_SITE_ID` | `demo` |
| `OPENFDD_SMOKE_DURATION_MINUTES` | `120` (720 if `OPENFDD_SMOKE_OVERNIGHT=true`) |
| `OPENFDD_SMOKE_POLL_SECONDS` | `60` |
| `OPENFDD_SMOKE_BASELINE_MINUTES` | `20` |
| `OPENFDD_SMOKE_CONFIRMATION_MINUTES` | `10` |
| `OPENFDD_SMOKE_CONFIRMATION_ROWS` | `10` |
| `OPENFDD_SMOKE_PRIMARY_SEMANTIC` | `duct-t` |
| `OPENFDD_SMOKE_FORCED_THRESHOLD_F` | `80.0` |

## Fault confirmation window

At 1-minute polling, `min_true_rows = 10` means the raw condition must remain true for about **10 minutes** before Open-FDD reports a **confirmed fault**. See [fault-confirmation.md](../rule-cookbook/fault-confirmation.md).

## Artifacts

Each run writes:

- `workspace/reports/bench_5007_long_fdd_<timestamp>.md`
- `workspace/reports/bench_5007_long_fdd_<timestamp>.json`
- `workspace/reports/bench_5007_long_fdd_<timestamp>_events.csv`

## Design

- **Data-model driven:** pairs BACnet/Niagara sensors via `metadata.cross_source_semantic`, `fdd_input`, `equipment_id`
- **Read-only:** polls devices; only Open-FDD rule thresholds change in evaluation payloads
- **Arrow/DataFusion evidence:** execution path recorded per backend; `python_list` core crunching fails the smoke
- **Confirmation honesty:** Python-loop confirmation engine reports `WARN` until vectorized

## API

Live mode uses `POST /api/bench/long-fdd/evaluate` for source-specific historian FDD evaluation.

## Related

- [Dual-source smoke](./bench-5007-dual-source-smoke.md)
- [Fault confirmation window](../rule-cookbook/fault-confirmation.md)
