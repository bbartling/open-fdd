# Bench 5007 dual-source smoke

Validates BACnet MS/TP device **5007** and Niagara baskStream station **bench9065** on the same physical bench.

## Run

```bash
./scripts/run_local.sh start
./scripts/smoke_bench_5007_dual_source.sh
```

Environment (optional):

| Variable | Default |
|----------|---------|
| `OPENFDD_BASE_URL` | `http://127.0.0.1:8765` |
| `OPENFDD_AUTH_ENV` | `workspace/auth.env.local` |
| `OPENFDD_SMOKE_SITE_ID` | `demo` |
| `OPENFDD_SMOKE_POLL_SECONDS` | `60` |
| `OPENFDD_SMOKE_DURATION_MINUTES` | `10` |

The script wraps `scripts/smoke_benserver_bench.py` and adds DataFusion SQL lab preview when `open-fdd[datafusion]` is installed.

## Paired semantic points

| Semantic | BACnet column | Niagara column |
|----------|---------------|----------------|
| oa-t | `oa-t` | `niagara-oa-t` |
| oa-h | `oa-h` | `niagara-oa-h` |
| duct-t | `duct-t` | `niagara-duct-t` |
| stat_zn-t | `stat_zn-t` | `niagara-stat-zn-t` |

Import `workspace/data/bench_dual_source_model.json` if the model is empty.
