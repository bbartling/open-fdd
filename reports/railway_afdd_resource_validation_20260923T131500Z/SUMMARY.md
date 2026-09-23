# Railway AFDD resource validation — config decision (2026-09-23)

**Source tip (in flight):** `tip/acme-afdd-24h-qual` @ PR #995 (+ memory-wire follow-up commits)  
**Deployed hub (at audit):** `ghcr.io/bbartling/openfdd-central:sha-f885fe4` / health `3.5.49+f885fe4066c0`  
**Do not claim FQ / OPS PINNED from this report.**

## Compaction correctness note

| Claim | Measured |
|-------|----------|
| Eligible multi-part plans after APPLY | **0** (`plan_after`) |
| Remaining Parquet files under `tenants/acme` | **38** (ssh find) |
| Remaining under hub `history/` | **42** |
| Size ACME / history | ~12 MiB / ~14 MiB |
| Zero eligible ≠ zero files | **Confirmed** — compacted monthly parts remain |

Row-count fingerprint / concurrent ingest+compact: **NOT RUN** on live hub (handoff: do not re-APPLY merely for a nicer report). Disposable fixture conservation: **NOT RUN**.

## Effective vs honored settings

| Setting | Effective Railway value | Code path | Honored on deployed `sha-f885fe4`? | Proposed | Restart? |
|---------|-------------------------|-----------|--------------------------------------|----------|----------|
| `OPENFDD_AFDD_MODE` | `continuous` | `AfddConfig::from_env` | **YES** (scheduler status mode=continuous) | **KEEP** | already redeployed |
| `OPENFDD_AFDD_INTERVAL_MINUTES` | `1440` | same | **YES** | **KEEP** (daily batch; detection latency ≤24h+interval) | — |
| `OPENFDD_AFDD_LOOKBACK_*` | `24` / `hours` | same | **YES** | **KEEP** | — |
| `OPENFDD_AFDD_BUILDING_ID` | `ACME` | timer scope | **YES** on timer; status `timer_scope` only after tip #995 | **KEEP** | tip re-pin |
| `OPENFDD_PARQUET_FLUSH_SECONDS` | `300` | `MicroBatchHistorian` | **YES** | **KEEP** with loss-window honesty: hard kill can lose ≤300s / ≤5000 rows per equip key buffered in RAM | already set |
| `OPENFDD_QUERY_MEMORY_MB` | `512` | `HistorianConfig` → `new_historian_session` | **NO on sha-f885fe4** — analytics/AFDD used bare `SessionContext::new()` | **KEEP 512** after tip wires bounded sessions; do **not** raise RAM hoping env alone helps | tip re-pin required |
| `OPENFDD_DATAFUSION_SPILL_DIR` | `/workspace/openfdd/df_spill` | same | **NO on sha-f885fe4** (dir absent / unused) | **KEEP**; verify mkdir after tip | tip re-pin |
| Railway service RAM/CPU | metrics ceiling ~8GB/8vCPU; plan name NOT VISIBLE | container | N/A | **NO CHANGE** until post-tip measurement | — |
| Private networking | mqtt/web→central internal DNS | already | YES | **NO CHANGE** | — |

## Concrete Railway diff (authorization required for anything not already applied)

### Already applied (this train — document, do not silently revert)

```diff
 # openfdd-central-cQ-F
+OPENFDD_AFDD_MODE=continuous
+OPENFDD_AFDD_INTERVAL_MINUTES=1440
+OPENFDD_AFDD_LOOKBACK_VALUE=24
+OPENFDD_AFDD_LOOKBACK_UNIT=hours
+OPENFDD_AFDD_BUILDING_ID=ACME
+OPENFDD_PARQUET_FLUSH_SECONDS=300
 # pre-existing:
  OPENFDD_QUERY_MEMORY_MB=512
  OPENFDD_DATAFUSION_SPILL_DIR=/workspace/openfdd/df_spill
```

### Proposed next (after tip GHCR green + backup) — **await operator ACK to apply image pin**

```diff
 # images (newest-by-created tip sha after #995 merge)
-openfdd-central: sha-f885fe4   (3.5.49)
-openfdd-mqtt:    sha-f885fe4
-openfdd-web:     sha-f885fe4
+openfdd-central: sha-<3.5.51 tip>
+openfdd-mqtt:    sha-<same>
+openfdd-web:     sha-<same>
 # fieldbus (bensbench): openfdd_fieldbus_railway_up.sh sha-<same>
```

**No** Hobby multi-subscription / no Timescale / no second central “worker” until post-tip matrix.

### Rollback

```text
# AFDD off (bulk) if continuous harms ingest:
OPENFDD_AFDD_MODE=bulk
# flush back:
OPENFDD_PARQUET_FLUSH_SECONDS=60
# images: prior OPS PINNED sha-7ad6479 / 3.5.43 or last known-good tip
```

## Targeted test ledger (this session)

| Test | Status | Evidence |
|------|--------|----------|
| Offline evaluator negatives | **PASS** | `test_afdd_evaluator_negatives.py` 6/6 |
| Gate 37 fail_closed detection (code) | **IMPLEMENTED** | not yet executed against hub |
| Gate 38 (live ACME run-now) | **NOT RUN** | needs tip with `timer_scope` + memory wire deployed; avoid competing MEGA |
| Analytics runtime fail_closed live | **NOT RUN** (pending tip) / prior tip pattern known | HTTP 200 + fail_closed is FAIL under new gate 37 |
| Ingest freshness (live) | **OBSERVED** | health `last_ingest_at` fresh; edges=1; reject=0 at audit |
| Timer continuity (1440 cadence) | **NOT RUN** | `recent_cycles=[]`; next_due ~24h after last_completed; run-now ≠ timer proof |
| QUERY_MEMORY honored live | **FAIL on deployed** / **FIXED in tip source** | bare SessionContext until re-pin |
| Full MEGA FQ | **NOT RUN** | coordinate after tip green — do not launch competing stress |

## Detection latency honesty

1440 min interval + 24h lookback = **daily batch AFDD**. Worst-case new-fault detection latency ≈ interval (24h) after telemetry watermark advances — **not** frequent AFDD evidence.

## Live bounded smoke (deployed `sha-f885fe4`)

| Check | Result |
|-------|--------|
| Ingest freshness | `last_ingest_at` fresh; edges=1; ingest_reject=0 |
| `POST /api/analytics/runtime` ACME 14d | HTTP 200 · **HAS_ROWS** n=38 · fail_closed=null (useful data — not FQ) |
| AFDD scheduler status | mode=continuous · 1440 · 24h · `timer_scope` **absent** on this digest · recent_cycles=[] · next_due ~24h |
| Gate 38 run-now | **NOT RUN** (await tip digest) |
| MEGA | **NOT RUN** (no competing stress) |

