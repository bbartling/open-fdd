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
3. `OPENFDD_SECURITY_EXECUTE=1 OPENFDD_MCP_IMAGE=ghcr.io/bbartling/openfdd-mcp:sha-<7> ./scripts/nightly-ot-bench/run_railway_hub_stress.sh`  
4. Cite `qualification_manifest.json` + generated `SUMMARY.md` (`fully_qualified` needs gates **19**+**35**+**25**/**25b**)  
5. BUG_REPORT + SESSION_LOG + **Current ops pin** → OPS PINNED; GH hygiene END  

## Agent rules

- **No Raspberry Pis** on the closeout path (bosspi / fake AHU / fake VAV freed).
- Railway is the AFDD head-end. Do not require local central for closeout.
- Stress is **LAST**. Do not cite older-pin stress as proof.
- ZAP = Railway public origin + `zap_baseline_verdict.py`; archive `reports/zap-railway_<TS>/`.
- **Security harness:** gates **25** / **25b** need `OPENFDD_SECURITY_EXECUTE=1` for FQ; dry-run alone is BLOCKED. In the Wave U field qualification profile, gate **26** requires candidate runtime ACL evidence; absent fixtures/tools are BLOCKED. N/A requires a profile applicability rule and supporting evidence. High=0; Medium only via reviewed dispositions JSON (never blanket `ACCEPT_ZAP_MEDIUM=1` without review).
- **Kali owns ActiveScan / exploratory PEN**; Mint runs gate 34 headers/`security.txt` + `preauth_disclosure` / gate 31 ACL. Skill: [`openfdd-mt-security`](../openfdd-mt-security/SKILL.md).
- **After ZAP:** `docker rm -f` leftover zap containers (low-RAM). One agent only — no duplicate Task workers on the same train.
- **`SKIP_ZAP=1` ⇒ not fully_qualified** (required gate SKIPPED). Never claim ZAP PASS when skipped.
- Railway MCP: exact image pin; `RAILWAY_ONLY=1` refuses local-central fallback in gate 13.
- Keep [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) **Current ops pin** + railway-cli skill synced on tip-in-flight and OPS PINNED.
- Do not rewrite historical PASS rows as if they used this enhanced suite.
- **Wave U acceptance correction (2026-09-20):** read `.cursor/plans/wave_u_independent_acceptance_audit.plan.md` and root `MILESTONES.md`. Both gate 36 tests must be machine-required for the promised closeout; scanner/observer errors, missing provenance or component-only evidence cannot qualify a candidate. The current runner needs the audit's repairs before its FQ label can close those milestones. A missing Nessus license blocks only the actual assessment, not readiness work.
- Machine port brain: [`docs/operations/recovery/AI_CONTEXT_HANDOFF.md`](../../../docs/operations/recovery/AI_CONTEXT_HANDOFF.md). Next program: 3.5.x patch train under `docs/operations/` / BUG_REPORT.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-railway-cli`](../openfdd-railway-cli/SKILL.md) — backup and re-pin
- [`openfdd-stack-ghcr`](../openfdd-stack-ghcr/SKILL.md) — image under test
- [`openfdd-mt-security`](../openfdd-mt-security/SKILL.md) — ZAP and tenant checks
