---
title: Stress closeout (nightly OT + Railway)
parent: Operations
nav_order: 6
nav_exclude: true

---

# Stress closeout — agent handbook

Canonical **rigorous stress LAST** protocol after a product tip lands on GHCR. Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md). Next-rev template: [`PATCH_CYCLE.md`](PATCH_CYCLE.md).

**Do not claim a train CLOSED** with only merge + one spot gate. Cite tip-pin artifacts (not an older `sha-*` stress run).

Entry point + profiles: [`scripts/qualification/README.md`](../../scripts/qualification/README.md).

## STRESS NOTE #1 — central RAM vs building / analytics load

Railway workspace plan is **Pro**. The `openfdd-central` replica memory limit is **24 GB**. The previous Hobby plan hard-capped replicas at **8 GB**. The 2026-09-28 crash was an OOM at that 8 GB cap under Overview / RCx analytics.

Closeout keeps the Pro headroom and watches metrics. Do not retune DataFusion, lookback, or query memory to squeeze the service back under the Hobby cap.

During Overview, RCx, and AFDD (including the ACME lab cycle), record:

| Watch | Where |
| --- | --- |
| Replica memory **limit / current / max** | Railway service metrics (cgroup cap; OOM source of truth) |
| Process / host RSS | Capacity sampler `capacity_samples.ndjson` → `capacity_report.json` (`memory_used_bytes`, `memory_percent_used`, `memory_source`) |
| Historian pressure | Same samples: `historian_file_count`, `historian_small_files`, `historian_bytes` |
| Building count | Package buildings / Jobs on the hub while analytics is running |

Replica limit and process RSS are different numbers. `/api/host/stats` on a shared node can report host RAM far above 24 GB (`memory_source=host_proc_likely_shared_node`). That percent is not the replica cap. Correlate RSS and file counts with how many buildings are loaded.

**Hard-fail the closeout** and clear `fully_qualified` when any of these show up, including when individual HTTP gates still returned PASS:

- silent restart (uptime reset, health flaps, Railway restart with no deploy)
- OOM (replica memory at the limit, container killed)
- 499 storm (gateway/client disconnects while analytics is in flight)

Sampler: [`scripts/nightly-ot-bench/lib_capacity_sample.sh`](../../scripts/nightly-ot-bench/lib_capacity_sample.sh), started by [`run_railway_hub_stress.sh`](../../scripts/nightly-ot-bench/run_railway_hub_stress.sh). Gate `24_capacity_pressure` is the analytics burst; gate `24b_capacity_report` records the rollup. Lead comment in the stress script is the same note.

## Three execution tiers

| Tier | Where | What | Not |
|------|--------|------|-----|
| **Per PR** | GitHub Actions / unit harness | Contract tests, AppSec (`appsec.yml`), fault-injection unit gates | Deploy credentials, OT access for untrusted forks |
| **Isolated candidate** | Disposable CI / lab stack | Digest-pinned images, synthetic seed, **authenticated** ZAP AF + MQTT ACL fixtures, endurance/restore | Live Railway OT writes; claiming Railway PASS from local smoke |
| **Railway field** | Railway hub + bensbench x86 fieldbus | CSV fault matrix, expected-edge telemetry, public baseline ZAP, auth role matrix, Railway MCP↔REST | Active payload scans, DoS, Pi fieldbus, local `react-ot` head-end |

Prior closeouts that said “authenticated deep ZAP out of scope” remain true for the **Railway field** tier. Authenticated ZAP belongs in the **isolated candidate** tier (tooling may ship ahead of a green disposable run — mark `BLOCKED` with prerequisites, do not substitute).

## Topology (3.3.20+)

| Role | Where | Purpose |
|------|--------|---------|
| **Hub** | Railway central + mqtt + web | AFDD / CSV / UI head-end |
| **Field** | bensbench **x86** `openfdd-fieldbus` only | MQTTS into Railway (`reseau.proxy.rlwy.net:44763`) |

Raspberry Pis are **out of** Open-FDD stress (bosspi / fake AHU `.13` / fake VAV `.14` freed). Do not stand up a local `react-ot` hub for patch-cycle closeout. Optional local `run_all` remains a lab recipe only.

## Bootstrap before stress

1. Tip Actions green + GHCR **Publish Open-FDD stack** success.
2. **Railway:** backup → re-pin central → mqtt → web — [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md) · skill [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md).
3. **Field:** `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` (stops local react-ot; host-net fieldbus → Railway). Kit via `POST /api/mqtt/edge-kits` (`bldg2` / `bensbench-1`).
4. Then `./scripts/nightly-ot-bench/run_railway_hub_stress.sh`.

Low-RAM: never local `docker build`; no local central/web/mqtt on the closeout path.

## Stress matrix (fill BUG_REPORT)

| # | Name | Command / artifact | Pass |
|---|------|--------------------|------|
| 0 | Hub + field + edges | gate `00_hub_health_edges` | Railway health `3.3.N+…`; fieldbus `:8081`; expected edge (or any) `has_telemetry:true` — **strict** probe chain |
| 0b | MQTTS → Overview charts | API overview/series + SPA Zone Other | Hosted-weather AV **9101** → role **`zone_t`**; **Zone Other** / MQTT generic zone charts populated (not empty with rising `ingest_ok`). Artifact or **DEFERRED** w/ operator-browser reason |
| 1 | Synthetic-59 | `--api-base` Railway | **59/59** (registry coverage reported separately when available) |
| 2 | Gate 17 | `RUN_SYNTH59_HEALTH_MATRIX=1` against Railway | health matrix + overview |
| 3 | B100 | `RAILWAY_ONLY=1` B100 spot | FC1 / runtime / series on Railway |
| 4 | Creekside | fixture + full zip | `LAKESIDE_ES` |
| 5 | Gate 19 | bundle validate | structural **READY** ≠ engineering/ML completeness |
| 6 | OWASP ZAP (light) | public `zap-baseline.py` + `zap_baseline_verdict.py` | High=0; Medium disposition explicit (`ACCEPT_ZAP_MEDIUM`); **not** authenticated AF |
| 7 | Auth role matrix | `scripts/qualification/auth_role_matrix.sh` | anon deny; admin/operator positive/deny per product contract |
| 8 | MCP accuracy | `railway_mcp_accuracy.sh` | exact `OPENFDD_MCP_IMAGE` sha-*; MCP↔REST parity; **no** local-central fallback |

### Continuous AFDD (ACME qual)

| # | Name | Command / artifact | Pass |
|---|------|--------------------|------|
| **19** | Synth AFDD flood | `2N_wave_m_afdd_flood.sh` | Budgeted registry flood on Synthetic-59 (authorized live) — **not** ACME continuous proof |
| **38** | **ACME continuous AFDD** | `38_acme_afdd_qualification.sh` | Hub `continuous` + **1440**/24h + `timer_scope=ACME`; live `run-now` ok; window ≤24h+5m (lookback-sized, not full history); durable `recent_cycles` — **continuous-AFDD SoT** |

Compact ACME hive parts before enabling continuous AFDD (`scripts/ops/railway_compact_hub.sh`). Recipe: [`AFDD_MODES.md`](AFDD_MODES.md) § ACME.

**Lookback-sized windows only.** `plan_continuous_cycle` (`crates/fdd_store/src/afdd_scheduler.rs`) sets `end` to the latest persisted telemetry watermark and `start` to `end − lookback`. The window stays the configured lookback. A cycle does not scan the whole historian, and `merge_windowed_rule_result` leaves result slices outside that window unchanged.

**Wall clock (product, not yet the field pin).** `OPENFDD_AFDD_SCHEDULE=wall_clock` with `OPENFDD_AFDD_WALL_CLOCK_HHMM` and `OPENFDD_AFDD_WALL_CLOCK_TIMEZONE` runs once per local day. The lab recipe is **05:00 America/Chicago** so the cycle can finish before the **06:00** digest, with lookback 24h. `OPENFDD_AFDD_INTERVAL_MINUTES=1440` remains the checkpoint-relative cadence when schedule kind is `interval`. The current field hub is still interval until this build is pinned. Soft-open: do not claim field qualification from the unit tests.

After downtime the next cycle is still one lookback-sized window (`catch_up`). Replaying a chosen range is `POST /api/afdd/scheduler/backfill` (`plan_bounded_backfill`). Scheduler config rejects `update_all`. Gate 38 checks config truth and a bounded `run-now` window. It records `schedule_kind` / `result_scope` when the hub sends them and does not require 05:00 until the field pin flips. Watch central RAM across that cycle (STRESS NOTE #1). Live lab env until re-pin: `OPENFDD_AFDD_MODE=continuous`, interval 1440, lookback 24 hours, `OPENFDD_AFDD_BUILDING_ID=ACME`.

### Truthful manifests (3.3.26+)

- Artifacts: `qualification_manifest.json` + generated `SUMMARY.md` under `reports/nightly-ot-bench_<TS>/`.
- Statuses: `PASS` | `FAIL` | `ERROR` | `SKIPPED` | `BLOCKED` | `NOT_APPLICABLE`.
- **`SKIP_ZAP=1` records `06_zap_baseline=SKIPPED` ⇒ not `fully_qualified`.** Do not emit a PASS sentence that claims ZAP ran.
- Missing/malformed ZAP JSON ⇒ `ERROR`.
- Mixed mqtt/fieldbus pins vs central/web tip ⇒ log hybrid compatibility; do not claim full-stack tip qualification.

### STRESS 6 notes (field ZAP — fluffy, not bug bounty)

- Target: public web origin only (SPA + `/api/health` / login). Operator-owned URL.
- Out of scope **on live hub:** authenticated deep crawl, MQTT/OT, DoS, activeScan against real buildings.
- In scope **isolated tier:** pinned ZAP AF plan, OpenAPI import, role contexts — see qualification README remaining blockers.
- Triage Low/Informational cookie noise in BUG_REPORT; fail-stop on High (and Medium unless explicitly accepted).

```bash
# Prefer the wrapper (records manifest + verdict parser):
./scripts/nightly-ot-bench/run_railway_hub_stress.sh

# Manual public baseline only (still parse JSON — do not trust -I alone):
ART="reports/zap-railway_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ART"
docker run --rm -v "$PWD/$ART:/zap/wrk:rw" -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t "$RAILWAY_PUBLIC_URL" -r zap_baseline.html -J zap_baseline.json -I
python3 scripts/qualification/zap_baseline_verdict.py --report "$ART/zap_baseline.json" --accept-medium
```

## Related product gates (3.3.20+)

| Gate | Purpose |
|------|---------|
| `scripts/gates/creekside_package_import_spot.sh` | Nested `openfdd_package_v1` + utilities wrapper |
| `scripts/nightly-ot-bench/19_engineering_bundle_validate.sh` | `openfdd_engineering_bundle_v1` structural validate |
| `scripts/openfdd_bundle_validate.py` | Offline bundle schema / READY |
| `scripts/qualification/*` | Manifest, ZAP verdict, auth matrix, Railway MCP |

Export / Dump UI: `/export` (nav label **Dump** after 3.3.22; alias `/wattlab`). Bundle API: `POST /api/jobs/{id}/exports`.  
Machine recreate: [`BENCH_RECOVERY.md`](BENCH_RECOVERY.md). Patch trains: [`patch_trains/`](patch_trains/).

## After stress

1. Flesh BUG_REPORT verdict with **this tip’s** artifact paths + `fully_qualified` from the manifest (not prior train).
2. `SESSION_LOG` entry with paths.
3. GH hygiene END: 0 open PRs, only `master`, tip Actions green.
4. Never rewrite older PASS claims as if they came from the enhanced suite.

## Anti-patterns

- Claiming CLOSED after merge without Railway CSV + edges + ZAP on **this** tip pin.
- Citing an older `sha-*` stress run as proof for a newer tip.
- `SKIP_ZAP=1` (or missing ZAP JSON) while advertising a ZAP PASS.
- Scanning non-owned hosts with ZAP.
- Putting Raspberry Pi fieldbus / fake-device Pis back on the closeout path.
- Standing up local `react-ot` as the AFDD head-end for a patch cycle.
- Local `docker build` of central/web on low-RAM benches.
- Gate 13 local-central fallback presented as Railway MCP evidence.
