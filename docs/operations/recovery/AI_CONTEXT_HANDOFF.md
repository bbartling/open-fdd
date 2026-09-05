---
title: AI context handoff (patch series)
parent: Operations
nav_order: 2
---

# AI / agent context handoff — Open-FDD patch series 3.3.21→3.3.26

**Read this first** on a new machine or new Cursor chat when continuing the train. Prefer **in-repo** sources over chat memory.

## Canonical files

| Priority | Path |
|----------|------|
| 1 | [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md) — living verdicts + Upcoming trains |
| 2 | [`patch_trains/openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md`](../patch_trains/openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md) |
| 3 | Active child under [`patch_trains/`](../patch_trains/) |
| 4 | [`BENCH_RECOVERY.md`](../BENCH_RECOVERY.md) — recreate field host |
| 5 | [`PATCH_CYCLE.md`](../PATCH_CYCLE.md) · [`STRESS_CLOSEOUT.md`](../STRESS_CLOSEOUT.md) |
| 6 | [`RAILWAY_DEPLOYMENT.md`](../RAILWAY_DEPLOYMENT.md) |
| 7 | Tuner baselines: [`recovery/lab_tuners_snapshot_pre_3.3.24.json`](lab_tuners_snapshot_pre_3.3.24.json) (~184) · [`recovery/vibe19_ui_tuners_snapshot.json`](vibe19_ui_tuners_snapshot.json) (~414) |

Optional local Cursor UI copies: `~/.cursor/plans/*.plan.md` (same content mirrored here).

## Locked decisions

- **Order:** 3.3.21 closeout → Dump IA (3.3.22) → Faults declutter (3.3.23) → tuner waves (3.3.24 GL36 → 3.3.25 SV/ECON/AHU → 3.3.26 gates/residual)
- **Tuners:** SQL-honest Lab expansion; **not** hard “match 414”
- **Topology:** Railway hub + bensbench **x86 fieldbus** + light ZAP; **no Pi**; **no** local react-ot closeout; **no** local docker build
- **Hygiene:** 0 open PRs / only `master` / tip Actions green at END of every rev
- **Skip:** only with **DEFERRED** row in BUG_REPORT

## Current product pain (why the trains exist)

1. ~~**Export & ML** tab = confusing multi-page~~ → **3.3.22 One Dump**
2. ~~**Faults** wall of settings~~ → **3.3.23** declutter
3. ~~GL36 Lab gaps~~ → **3.3.24**; ~~SV/ECON partial~~ → **3.3.25**
4. **3.3.26 (active):** qualification harness honesty (manifests, SKIP_ZAP, auth, Railway MCP); operational-gate Lab trio **DEFERRED** (Path B)
5. Stress entry: [`scripts/qualification/README.md`](../../../scripts/qualification/README.md) · cite `fully_qualified` from manifest

## Runtime facts (verify on tip — do not assume)

- Public web: `https://openfdd-web-production-af99.up.railway.app`
- MQTTS proxy: `reseau.proxy.rlwy.net:44763`
- Railway project: `gleaming-cooperation` / `production`
- Central service id name: `openfdd-central-cQ-F`
- Field site/edge often `bldg2` / `pi-1` (kit reuse — CA key may be missing on Railway)
- Last CLOSED hub: `3.3.25+e78a608934ed` central/web `sha-e78a608`; mqtt/fieldbus often still `sha-b3004aa` (hybrid DEFERRED)

## Agent loop (every shipping rev)

```text
hygiene START → VERSION bump (if shipping) → one concern → one PR
  → squash-merge --delete-branch → wait GHCR Publish sha-<7>
  → railway backup → re-pin central→mqtt→web → openfdd_fieldbus_railway_up.sh
  → run_railway_hub_stress.sh LAST → BUG_REPORT Verdict → hygiene END
```

Low-RAM: `scripts/openfdd_docker_maintenance.sh` non-aggressive only; never `docker build` central/web on bench.

## Do not

- Force-push / `--no-verify` / commit secrets or OT LAN IPs
- Reopen #763 / #805 ML depth
- Parallel feature PRs across trains
- Claim CLOSED using older `sha-*` stress dirs

## SESSION_LOG

Append paths under [`openfdd_agent_spec/SESSION_LOG.md`](../../openfdd_agent_spec/SESSION_LOG.md) when closing a Verdict.
