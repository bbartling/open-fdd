# Wave P / Wave R — Residual stress + GH tidy tracker

**Parent:** [`BUG_REPORT_WAVE_O.md`](BUG_REPORT_WAVE_O.md) Soft residuals · Wave R plan [`wave_r_stress_patches_5406b539.plan.md`](../../.cursor/plans/wave_r_stress_patches_5406b539.plan.md)

## Tip / GHCR / Railway

| Item | Status |
|------|--------|
| Product tip | **OPS PINNED 3.5.22** / `sha-4d3a6b0` (#936) · health `3.5.22+4d3a6b0e0707` · `multi_tenant=true` |
| Harness tip | `4c0862e1` (#937) synth59 hours rel-tol + AFDD bearer / auth fetch |
| Backup | `20260915T232819Z` (+ release backups under `~/openfdd-releases/`) |
| Hub stress | `reports/nightly-ot-bench_20260916T011952Z/` · **`fully_qualified=true`** · no `SKIP_ZAP` |

## Soft-OPEN (≤ Stage C)

| ID | Note |
|----|------|
| **stage-c-idp-mfa-sku** | Commercial IdP/MFA/SKU |
| **util-interval** | `utility_interval` relation missing → `rules_failed` Soft; live AFDD flood ignores |
| **r6-ingest-reject** | Count on `/api/health` + `/api/ingest/stats` only; ACME honesty (no invent ΔP SP / TEC ghosts / OAT-METEO) |
| **kali-zap-af** | Authenticated ZAP AF remains Kali-owned |
| **wave-o1-tenant-path-migrate** | Hub-root `building=*` still; optional `tenants/{tid}/` migrate |
| **p2c-mqtt-acl-staging** | Broker ACL proof = Kali staging |
| **historian-n-building-scale** | Small Parquet parts × N buildings; offline H4 now; runtime compaction Soft later |
| **admin-capacity-gauges** | Volume/cgroup/historian gauges — not host MemTotal charts |
| **railway-capacity-stress** | S5a sampler + gate 24 wired; cite `capacity_report.json` on next mega |
| **mqtt-pause-ui** | Option A parked (streaming pause; not fieldbus stop) |

## Wave R closeout (2026-09-16)

| ID | Status | Note |
|----|--------|------|
| **r1** | **CLOSED** | FC1 SQL `fan_status` parity (#936); soak ~39.58h vs golden 40 via rel-tol (#937) |
| **r2** | **CLOSED** | Wave L OFF 12–17 PASS N/A when MT ON |
| **r3** | **CLOSED** | AFDD pre-minted bearer; gate 19 PASS |
| **r4** | **CLOSED** | ZAP baseline PASS (`ACCEPT_ZAP_MEDIUM=1`) |
| **r5** | **CLOSED** | Hub pin `sha-4d3a6b0` / 3.5.22 |
| **r6** | Soft | ingest_reject count Soft + ACME honesty |
| **r7** | **CLOSED** | JCI FEC **5007** Who-Is + AI:1173 |
| **r10** | **CLOSED** | Viewer optional; Railway has `OPENFDD_VIEWER_PASSWORD` |
| **r11** | Soft | UTIL-INTERVAL (not FC1) |
| **r12** | Parked | Stage C |
| **r13** | **OPS PINNED** | Stress `20260916T011952Z` fully_qualified |

## Exit (P9 / R)

**Done:** tip GHCR + Railway re-pin + ONE full `run_railway_hub_stress.sh` cited + 0 open wave PRs + Soft-OPEN ≤ Stage C.
