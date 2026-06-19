---
title: Bench 5007 half-hour smoke
parent: Operations
nav_order: 14
---

# Bench 5007 half-hour smoke

30-minute validation for **device 5007** on the bench site (`demo`):

- **PyArrow vs DataFusion SQL** parity (`smoke-paired-zn-t-bacnet-*` and Niagara twins)
- **API health** (`/api/health`, bench poll status)
- **BACnet P8 override scan** — hourly rotation, one device per cycle (`/api/bacnet/overrides/status`)
- **Frontend** — SPA index + static assets (optional browser console with playwright)
- **Service logs** — bounded tail scan for ERROR/Exception lines
- **RCx DOCX** — smoke results embedded in `smoke_validation` section

## Cursor / SSH safe launch

Never block-wait from a Cursor agent (crashes IDE on 30 min sleeps).

```bash
./scripts/run_local.sh start
./scripts/smoke_bench_5007_half_hour.sh
./scripts/smoke_bench_5007_half_hour_status.sh
```

Artifacts:

| File | Content |
|------|---------|
| `reports/paired_fdd_smoke_validation.{md,json}` | FDD parity cycles |
| `reports/bench_5007_half_hour_health.json` | Health probe history |
| `reports/bench_5007_half_hour_smoke_rcx_*.docx` | RCx report with smoke section |

Regenerate RCx only:

```bash
python3 scripts/generate_half_hour_smoke_rcx_report.py
```

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENFDD_SMOKE_HEALTH_PROBES` | on for `--short --bench-only` | API/UI/log probes every 5 min |
| `OPENFDD_SMOKE_RCX_REPORT` | `1` | Build DOCX at end |
| `OPENFDD_SMOKE_FRONTEND_BROWSER` | off | JS console capture (needs playwright + chromium) |

## Override scan expectations

Commission agent runs `bacnet_override_scan_loop` with `OFDD_OVERRIDE_SCAN_INTERVAL_S=3600` (one device per hour). The smoke validates:

- `scan_interval_s ≈ 3600`
- `operator_priority = 8` (P8)
- `device_count ≥ 1` and cursor present
- Override summary flows into RCx `model_health` / analyst override notes via `build_rcx_report_context()`
