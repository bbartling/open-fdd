---
title: Patch cycle (tiny rev)
parent: Operations
nav_order: 3
---

# Patch cycle — tiny VERSION rev + Railway hub stress

Copy this file’s **Cursor plan YAML** into `.cursor/plans/patch_cycle_3.3.N_<slug>.plan.md` for the next train. Bump **N** every GHCR-shipping cycle.

**Hub:** Railway (central → mqtt → web).  
**Field:** bensbench **x86** `openfdd-fieldbus` only → Railway MQTTS.  
**Pis:** not in Open-FDD stress (freed for vibe13 / other benches).

Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md). Stress handbook: [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md).  
**Machine death / new bench:** [`BENCH_RECOVERY.md`](BENCH_RECOVERY.md). **AI handoff:** [`recovery/AI_CONTEXT_HANDOFF.md`](recovery/AI_CONTEXT_HANDOFF.md).  
**Active series (3.3.21–3.3.26):** [`patch_trains/`](patch_trains/) (mirrored Cursor plans — keep GitHub as source of truth).

## Rev bump rule

| When | VERSION |
|------|---------|
| Ships stack images to GHCR (docs+harness+ops that retarget nightly) | `3.3.N` → `3.3.N+1` in `VERSION` + workspace `Cargo.toml` + `edge` / `services/*` / `crates/openfdd_{contracts,mqtt}` |
| Pure evidence / BUG_REPORT after publish | No bump |
| PyPI `open-fdd` | Do **not** bump unless the Python package changed |

After publish, pin **`sha-<7>`**. Health must read `3.3.N+<fullsha-prefix>`.

## Cursor plan YAML (paste + fill N)

```yaml
---
name: 3.3.N patch cycle
overview: Tiny VERSION 3.3.(N-1)→3.3.N. x86 fieldbus → Railway MQTTS. CSV + ZAP stress LAST. Low-RAM. 0 stale PRs/branches/failed Actions.
todos:
  - id: p0-hygiene
    content: GH hygiene START — 0 open PRs; only master; tip Actions green
    status: pending
  - id: p1-version
    content: Bump VERSION + Cargo 3.3.(N-1) → 3.3.N
    status: pending
  - id: p2-fix
    content: Product/ops fix for this rev (one concern)
    status: pending
  - id: p3-pr
    content: One PR; squash-merge --delete-branch; wait GHCR Publish
    status: pending
  - id: p4-repin
    content: Railway backup + re-pin central→mqtt→web; x86 fieldbus same sha-*
    status: pending
  - id: p5-stress
    content: ./scripts/nightly-ot-bench/run_railway_hub_stress.sh (CSV + ZAP)
    status: pending
  - id: p6-bug-report
    content: BUG_REPORT verdict 3.3.N + SESSION_LOG artifact paths
    status: pending
  - id: p7-hygiene-end
    content: GH hygiene END — 0 PRs; only master; tip Actions green
    status: pending
isProject: false
---
```

## Loop (every rev)

```text
hygiene → VERSION bump + one fix → PR merge → GHCR sha-*
  → Railway backup → re-pin hub → x86 fieldbus up
  → run_railway_hub_stress.sh → BUG_REPORT → hygiene
```

```bash
# 1) backup + re-pin (see railway-cli skill)
./scripts/railway_central_workspace_backup.sh
SHA=sha-<7>
# railway service source connect … central → mqtt → web

# 2) field only on this machine
./scripts/openfdd_fieldbus_railway_up.sh "$SHA"

# 3) stress LAST (Railway CSV + ZAP)
export OPENFDD_API_BASE=https://openfdd-web-production-af99.up.railway.app
./scripts/nightly-ot-bench/run_railway_hub_stress.sh
```

## Stress matrix (fill BUG_REPORT)

| # | Gate | Pass |
|---|------|------|
| 0 | Hub health + x86 fieldbus + `/api/edges` telemetry | `3.3.N+…`; `has_telemetry:true` |
| 1 | synth59 `--api-base` Railway | **59/59** |
| 2 | Gate 17 | health matrix + overview |
| 3 | B100 `RAILWAY_ONLY=1` | FC1 / runtime / series |
| 4 | Creekside fixture + full zip | `LAKESIDE_ES` |
| 5 | Gate 19 | **READY** |
| 6 | ZAP baseline Railway public URL | no unexplained High/Critical |

## Anti-patterns

- Raspberry Pi fieldbus or fake-device Pis in the closeout path
- Local `react-ot` hub as the AFDD head-end
- Local `docker build` on bensbench
- Citing an older `sha-*` stress run for a newer tip
- Leaving open PRs / feature branches after merge
