---
name: openfdd-stress-closeout
description: >-
  Use when closing a patch cycle with rigorous stress LAST on the Railway hub,
  bensbench x86 fieldbus → MQTTS, CSV/synth59/Creekside/gate 19, B100 Railway-only,
  light OWASP ZAP, auth role matrix, Railway MCP accuracy, or qualification
  manifests. Triggers on: run_railway_hub_stress, RAILWAY_ONLY, synth59,
  gate 17, gate 19, zap-baseline, qualification_manifest, SKIP_ZAP, PATCH_CYCLE, 3.3.N rev.
---

# Stress closeout (Open-FDD)

Full handbook: [`docs/operations/STRESS_CLOSEOUT.md`](../../../docs/operations/STRESS_CLOSEOUT.md)  
Rev template: [`docs/operations/PATCH_CYCLE.md`](../../../docs/operations/PATCH_CYCLE.md)  
Qualification entry: [`scripts/qualification/README.md`](../../../scripts/qualification/README.md)  
Field up: [`scripts/openfdd_fieldbus_railway_up.sh`](../../../scripts/openfdd_fieldbus_railway_up.sh)  
Railway CLI: [`openfdd-railway-cli`](../openfdd-railway-cli/SKILL.md)

## Tiers (do not conflate)

- **Railway field** — `run_railway_hub_stress.sh` (read-oriented + public ZAP).
- **Isolated candidate** — authenticated ZAP AF / MQTT ACL / restore (not live OT).
- **Per PR** — unit + AppSec workflows.

## Order

1. Tip GHCR publish green → Railway backup + re-pin (central→mqtt→web)  
2. `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` (stops local react-ot)  
3. `OPENFDD_MCP_IMAGE=ghcr.io/bbartling/openfdd-mcp:sha-<7> ./scripts/nightly-ot-bench/run_railway_hub_stress.sh`  
4. Cite `qualification_manifest.json` + generated `SUMMARY.md` (`fully_qualified`)  
5. BUG_REPORT + SESSION_LOG → GH hygiene END  

## Agent rules

- **No Raspberry Pis** on the closeout path (bosspi / fake AHU / fake VAV freed).
- Railway is the AFDD head-end. Do not require local central for closeout.
- Stress is **LAST**. Do not cite older-pin stress as proof.
- ZAP = Railway public origin + `zap_baseline_verdict.py`; archive `reports/zap-railway_<TS>/`.
- **After ZAP:** `docker rm -f` leftover zap containers (low-RAM). One agent only — no duplicate Task workers on the same train.
- **`SKIP_ZAP=1` ⇒ not fully_qualified** (required gate SKIPPED). Never claim ZAP PASS when skipped.
- Railway MCP: exact image pin; `RAILWAY_ONLY=1` refuses local-central fallback in gate 13.
- Do not rewrite historical PASS rows as if they used this enhanced suite.
- Machine port brain: [`docs/operations/recovery/AI_CONTEXT_HANDOFF.md`](../../../docs/operations/recovery/AI_CONTEXT_HANDOFF.md). Next program: 3.3.27+ nightly bug train under `docs/operations/patch_trains/`.
