---
name: openfdd-stress-closeout
description: >-
  Use when closing a nightly/product train with rigorous stress LAST, dual
  pipeline (Railway + local), BUG_REPORT evidence, Creekside/gate 19/bundle,
  or light OWASP ZAP on Railway. Triggers on: run_all, stress closeout,
  synthetic-59, gate 17, B100 parity, gate 19, zap-baseline, STRESS 1–7,
  WEATHER_SOAK_SECS, SKIP_PULL.
---

# Stress closeout (Open-FDD)

Full handbook: [`docs/operations/STRESS_CLOSEOUT.md`](../../../docs/operations/STRESS_CLOSEOUT.md)  
Local hub (HTTP / no TLS): [`docs/operations/LOCAL_DEPLOYMENT.md`](../../../docs/operations/LOCAL_DEPLOYMENT.md)  
Railway CLI re-pin: [`openfdd-railway-cli`](../openfdd-railway-cli/SKILL.md)  
Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../../../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Order (non-negotiable)

1. Tip GHCR publish green → Railway backup + re-pin (central→mqtt→web) → local `react-ot` re-pin → bosspi if in scope  
2. Smoke 01/06/10/18 + Pipeline A  
3. STRESS 1–6 on tip pin (`run_all` → synth59 → gate17 → B100 → Creekside → gate19)  
4. STRESS 7 light ZAP on **Railway public HTTPS** only (optional fluffy AppSec)  
5. BUG_REPORT + SESSION_LOG with **this tip’s** artifact paths → GH hygiene END  

## Quick commands

```bash
SHA=sha-<7>
export OPENFDD_IMAGE_TAG="$SHA" WEATHER_SOAK_SECS=120
unset SKIP_PULL

./scripts/railway_central_workspace_backup.sh   # before hub re-pin
# railway service source connect …  (see railway-cli skill)

./scripts/openfdd_maint_update_resume.sh react-ot "$SHA" --skip-maintenance
./scripts/nightly-ot-bench/run_all.sh
# … then STRESS 2–7 per STRESS_CLOSEOUT.md
```

## Agent rules

- Stress is **LAST** — never before tip re-pin.
- Do not cite older-pin stress as proof for a newer tip.
- Local dashboard = **HTTP behind firewall**; no product TLS yet.
- ZAP = Railway public origin only; not bug-bounty depth; archive under `reports/zap-railway_<TS>/`.
- MCP/FDD tools ≠ Railway CLI (deploy) ≠ Railway platform MCP.
