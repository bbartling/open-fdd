---
title: Paired FDD smoke (bench + Acme)
nav_order: 12
---

# Paired FDD smoke

Hardcoded cross-site validation: **bensserver bench 5007** and **Acme** run the **same schedule** with mid-test fault-parameter toggles. PyArrow and DataFusion SQL rules must agree on flagged row counts.

## What is tested

| Site | Rule | Normal phase | Blatant phase |
|------|------|--------------|---------------|
| Bench (`demo`) | `stat_zn-t` bounds on BACnet 5007 + Niagara bench9065 | 65–75 °F | 99–100 °F |
| Acme | Local `oa-t` vs `web-oat-t` spread | ≤ 10 °F | ≤ 0.001 °F |

Rule IDs are fixed in `open_fdd/validation/paired_fdd_contract.py`. Each site has **arrow** and **datafusion_sql** variants.

## Fault confirmation (5 minutes)

All paired smoke rules use:

```json
{"min_elapsed_minutes": 5, "min_true_rows": 5, "poll_interval_s": 60}
```

A condition must stay true for **~5 minutes** before it counts as a confirmed fault. See [Fault confirmation](../rule-cookbook/fault-confirmation.md).

## Modes (hardcoded)

| Mode | Duration | Toggle interval |
|------|----------|-----------------|
| `tryout` | 6 min | 3 min |
| `short` | 30 min | 15 min |
| `standard` | 2 h | every 15 min |
| `overnight` | 12 h | every 15 min |

Toggles alternate **normal** ↔ **blatant** fault parameters via the rules API (same as an operator or AI agent adjusting thresholds mid-run).

## Run detached (required for in-depth runs)

Bench **5007** + **Acme** paired smoke runs for **30 minutes to 12 hours**. Always start **short**, **standard**, and **overnight** **detached** — from a plain terminal or via `--detached` — so Cursor, SSH, or IDE disconnects do not kill the harness.

**Recommended** (wrapper re-invokes itself under `nohup`):

```bash
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --short --detached
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --standard --detached
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --overnight --detached
```

Logs: `/tmp/paired_fdd_smoke_<mode>_*.log` · PID file: `/tmp/paired_fdd_smoke_<mode>.pid` · `tail -f` the log to watch progress.

**Manual `nohup`** (equivalent):

```bash
nohup env OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --overnight \
  > /tmp/paired_fdd_overnight.log 2>&1 &
echo $! > /tmp/paired_fdd_overnight.pid
```

`--tryout` (6 min) may run attached for quick dev checks.

## Run

Prereqs: local stack on `:8765`, Acme edge on matching GHCR image, `OPENFDD_LIVE_ACME=1`.

```bash
OFDD_SKIP_UI_BUILD=1 ./scripts/run_local.sh start
OPENFDD_IMAGE_TAG=3.1.4 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling

OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --tryout          # attached OK
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --short --detached
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --standard --detached
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --overnight --detached
```

`scripts/smoke_sites_parity.sh` delegates to this harness.

## Reports

- `reports/paired_fdd_smoke_validation.md`
- `reports/paired_fdd_smoke_validation.json`
- `reports/site_parity_smoke.json` (UI bundle + API revision parity)

## Pass criteria

- Site parity smoke passes (matching UI hash, no 401 on health endpoints).
- No PyArrow vs SQL flagged-count mismatch per cycle.
- No save/batch API errors in either site loop.

Blatant-phase fault counts may be zero on Acme when the historian is still on demo fallback — check feather ingest and live OAT columns before overnight runs.
