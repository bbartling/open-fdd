---
title: Paired FDD smoke (bench + Acme)
nav_order: 12
---

# Paired FDD smoke

Hardcoded cross-site validation: **bensserver bench 5007** and **Acme** run the **same schedule** with mid-test fault-parameter toggles. PyArrow and DataFusion SQL rules must agree on flagged counts **and** row-level fault masks (CI golden fixtures).

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

## Run (local bench)

Prereqs: local stack on `:8765`.

```bash
OFDD_SKIP_UI_BUILD=1 ./scripts/run_local.sh start
./scripts/smoke_paired_fdd_harness.sh --tryout
```

## Run detached (required for in-depth runs)

**Do not run long smokes attached from Cursor** — they crash the IDE when agents poll/wait. Use the systemd-isolated launcher (no terminal parent):

```bash
# benserver bench only (recommended for local UI iteration)
./scripts/run_paired_fdd_smoke_isolated.sh --short --bench-only

# bench + Acme FDD (skips UI bundle parity by default)
OPENFDD_LIVE_ACME=1 ./scripts/run_paired_fdd_smoke_isolated.sh --short

# Poll status — read-only, safe for agents (never tail -f / wait)
./scripts/smoke_paired_fdd_status.sh --mode short
```

Legacy wrapper (also uses isolated launcher when `--detached`):

```bash
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --short --detached
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --standard --detached
OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --overnight --detached
```

`OPENFDD_LIVE_ACME=1` is required for live Acme paired runs (site parity + remote loop).

Logs: `/tmp/paired_fdd_smoke_<mode>_*.log` · Status JSON: `/tmp/paired_fdd_smoke_<mode>.status.json` · Cycle log: `/tmp/paired_fdd_smoke_<mode>_cycles.jsonl`

**Monitor outside Cursor** (tmux/SSH). Heartbeat every 5 minutes; status JSON updates each poll cycle.

```bash
cat /tmp/paired_fdd_smoke_overnight.status.json
grep heartbeat /tmp/paired_fdd_smoke_overnight_*.log | tail -3
```

Bundle for download:

```bash
./scripts/bundle_paired_fdd_smoke_report.sh --mode overnight
# Windows: scp ben@bensserver:/tmp/paired_fdd_smoke_bundle.zip C:\Users\ben\Downloads\
```

## Auth refresh (overnight harness)

The harness uses `scripts/smoke_paired_fdd_auth.py`:

1. Decodes JWT `exp` (no signature verification) and re-logins before expiry (~2 min skew).
2. On HTTP **401**, retries the request **once** after re-login.
3. Successful retry is an **auth_refresh_event** (not an FDD failure).
4. Unrecoverable 401 stops the site loop and sets `auth_failure` in status JSON.

Status/report fields: `auth_refresh_count`, `auth_401_count`, `auth_first_401_at`, `auth_recovered_count`, `auth_unrecovered_count`, `first_unrecoverable_auth_failure_at`.

**Security-negative checks preserved:** expired, tampered, missing, or wrong-role tokens still fail. The harness does not disable auth or log tokens/secrets.

## Arrow vs DataFusion SQL parity

**Live harness:** compares paired batch runs (flagged/rows counts + analytics when present) via `open_fdd/validation/paired_fdd_parity.py`.

**CI (no live site):** `open_fdd/tests/validation/test_datafusion_arrow_parity.py` runs golden tables through PyArrow + DataFusion and asserts identical fault masks (`true_count`, `false_count`, `null_count`, row-level match).

Live Acme tests remain behind `OPENFDD_LIVE_ACME=1`.

## RCx report smoke

Fixture-driven DOCX validation (no live historian):

```bash
python3 scripts/smoke_rcx_report.py
python3 -m pytest open_fdd/tests/reports/test_rcx_docx_fixtures.py -q
```

Live edge RCx: `POST /api/reports/rcx/generate` on a running stack (integrator auth required).

## Niagara massive-site / folder mapping (#315)

UI: **Niagara** tab → **Station tree browse** — pick a folder as building boundary, set `default_points_root`, preview before discover.

Helpers: `open_fdd/validation/niagara_folder_mapping.py` · tests: `open_fdd/tests/validation/test_niagara_folder_mapping.py`

Dry-run poll: use **Poll once** after discovery; check Activity log and driver tree counts.

## Reports

- `reports/paired_fdd_smoke_validation.md` / `.json`
- `reports/site_parity_smoke.json`

## Pass criteria

- Site parity smoke passes (matching UI hash, health OK).
- No PyArrow vs SQL parity mismatch per cycle (counts + batch analytics).
- No unrecoverable auth failures during the run.
- Auth refresh events are allowed and not counted as FDD failures.

`scripts/smoke_sites_parity.sh` delegates to this harness.
