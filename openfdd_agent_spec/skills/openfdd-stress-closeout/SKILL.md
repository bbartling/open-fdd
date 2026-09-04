---
name: openfdd-stress-closeout
description: >-
  Use when closing a patch cycle with rigorous stress LAST on the Railway hub,
  bensbench x86 fieldbus → MQTTS, CSV/synth59/Creekside/gate 19, B100 Railway-only,
  or light OWASP ZAP. Triggers on: run_railway_hub_stress, RAILWAY_ONLY, synth59,
  gate 17, gate 19, zap-baseline, PATCH_CYCLE, 3.3.N rev.
---

# Stress closeout (Open-FDD)

Full handbook: [`docs/operations/STRESS_CLOSEOUT.md`](../../../docs/operations/STRESS_CLOSEOUT.md)  
Rev template: [`docs/operations/PATCH_CYCLE.md`](../../../docs/operations/PATCH_CYCLE.md)  
Field up: [`scripts/openfdd_fieldbus_railway_up.sh`](../../../scripts/openfdd_fieldbus_railway_up.sh)  
Railway CLI: [`openfdd-railway-cli`](../openfdd-railway-cli/SKILL.md)

## Order

1. Tip GHCR publish green → Railway backup + re-pin (central→mqtt→web)  
2. `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` (stops local react-ot)  
3. `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` (CSV + ZAP)  
4. BUG_REPORT + SESSION_LOG → GH hygiene END  

## Agent rules

- **No Raspberry Pis** on the closeout path (bosspi / fake AHU / fake VAV freed).
- Railway is the AFDD head-end. Do not require local central for closeout.
- Stress is **LAST**. Do not cite older-pin stress as proof.
- ZAP = Railway public origin only; archive `reports/zap-railway_<TS>/`.
