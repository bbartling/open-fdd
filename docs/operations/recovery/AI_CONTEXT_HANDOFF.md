---
title: AI context handoff (patch series)
parent: Operations
nav_order: 2
---

# AI / agent context handoff — Open-FDD (machine port)

**Read this first** on a new machine or new Cursor chat. Prefer **in-repo** sources over chat memory. This file is the portable brain when bensbench dies.

## Machine / RAM constraints (bensbench x86)

- Host is **low-RAM / last-leg**. Prefer docs + script edits; **never** `docker build` central/web/fieldbus here.
- **One Cursor agent** per train — no parallel Task/subagents for the same patch cycle.
- After stress/ZAP: `docker rm -f` leftover `zap` / disposable MCP containers; keep only `openfdd-edge-fieldbus-1` if field telemetry is needed.
- Push commits often so an SSH drop does not lose work.
- Recreate field host: [`BENCH_RECOVERY.md`](../BENCH_RECOVERY.md).

## Canonical files (priority order)

| # | Path | Why |
|---|------|-----|
| 1 | [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md) | Living verdicts + Upcoming trains |
| 2 | [`patch_trains/openfdd_nightly_bug_train_3.3.27_plus_program.plan.md`](../patch_trains/openfdd_nightly_bug_train_3.3.27_plus_program.plan.md) | **Active** program index (3.3.27+) |
| 3 | Active child under [`patch_trains/`](../patch_trains/) | One concern per nightly |
| 4 | [`scripts/qualification/README.md`](../../../scripts/qualification/README.md) | Stress entry; cite `fully_qualified` |
| 5 | [`STRESS_CLOSEOUT.md`](../STRESS_CLOSEOUT.md) · [`PATCH_CYCLE.md`](../PATCH_CYCLE.md) | Handbook + rev template |
| 6 | [`RAILWAY_DEPLOYMENT.md`](../RAILWAY_DEPLOYMENT.md) | Hub re-pin |
| 7 | [`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md) · [`CONTAINER_AGENT.md`](../../openfdd_agent_spec/CONTAINER_AGENT.md) | Agent rules |
| 8 | Predecessor (CLOSED): [`patch_trains/openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md`](../patch_trains/openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md) | Historical series |

Mirror Cursor UI plans from `docs/operations/patch_trains/` → `~/.cursor/plans/` (GitHub is source of truth).

## Locked decisions

- **Topology:** Railway hub (central→mqtt→web) + bensbench **x86 fieldbus** → MQTTS; **no Pi** on closeout; **no** local `react-ot` as AFDD head-end
- **Stress LAST:** `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` → `qualification_manifest.json` `fully_qualified`
- **Skip:** only **DEFERRED** in BUG_REPORT
- **Hygiene:** 0 open PRs / only `master` / tip Actions green at END

## Series status

| Series | Status |
|--------|--------|
| 3.3.21→3.3.26 (Dump / Lab / tuners / qual harness) | Close **3.3.26** then mark program done |
| **3.3.27+ nightly bug train** | Next — pin sync → Lab residual → viewer/UI → isolated ZAP → MQTTS → restore/perf |

## Runtime facts (verify on tip — do not assume)

- Public web: `https://openfdd-web-production-af99.up.railway.app`
- MQTTS proxy: `reseau.proxy.rlwy.net:44763`
- Railway project: `gleaming-cooperation` / `production`
- Central service: `openfdd-central-cQ-F`
- Field kit often `bldg2` / `pi-1` (CA key may be missing on Railway mqtt volume)
- Hybrid pin debt: mqtt/fieldbus may lag central/web (`sha-b3004aa`) — clear in **3.3.27** or DEFER with Publish URLs

## Agent loop (every shipping rev)

```text
hygiene START → VERSION bump → one concern → one PR
  → squash-merge --delete-branch → wait GHCR Publish sha-<7>
  → railway backup → re-pin central→mqtt→web → openfdd_fieldbus_railway_up.sh
  → run_railway_hub_stress.sh LAST → docker cleanup ZAP leftovers
  → BUG_REPORT Verdict → SESSION_LOG → hygiene END
```

## Do not

- Force-push / `--no-verify` / commit secrets or OT LAN IPs
- Reopen #763 / #805 ML depth
- Parallel feature PRs or duplicate agents on the same train
- Claim CLOSED using older `sha-*` stress dirs
- Leave ZAP / disposable MCP containers running after stress
- Local `docker build` of central/web on low-RAM benches

## SESSION_LOG

Append paths under [`openfdd_agent_spec/SESSION_LOG.md`](../../openfdd_agent_spec/SESSION_LOG.md) when closing a Verdict.
