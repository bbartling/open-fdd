# Wave P / Wave R — Residual stress + GH tidy tracker

**Parent:** [`BUG_REPORT_WAVE_O.md`](BUG_REPORT_WAVE_O.md) Soft residuals · Wave R plan [`wave_r_stress_patches_5406b539.plan.md`](../../.cursor/plans/wave_r_stress_patches_5406b539.plan.md)

## Tip / GHCR / Railway

| Item | Status |
|------|--------|
| Product tip | **TIP TRAIN `3.5.27` (branch `fix/wave-ux-soft-tip-a-3527`)** · Soft UX #1–#5 + mqtt-pause gate 35 · awaiting GHCR + Railway re-pin · prior OPS PINNED `3.5.26` / `sha-2c4c2d9` |
| Prior tip | `3.5.26` / `sha-2c4c2d9` (#944 tip-completeness YAML) · hub backup `20260917T020217Z` · health `3.5.26+2c4c2d9e02e9` |
| Prior hub | `sha-f318dbc` / 3.5.24 · backup `20260916T215014Z` · Soft Park S5 `20260916T215804Z` |
| Prior OPS PINNED | Wave R **3.5.22** / `sha-4d3a6b0` (#936) · stress `20260916T011952Z` **`fully_qualified=true`** |
| Soft Park S5 | Stress `reports/nightly-ot-bench_20260916T215804Z/` · **22 PASS / 4 FAIL** · not `fully_qualified` · `capacity_report.json` ok (34 samples, Δ ingest_ok +88, 0 health flaps) · FAILs: 00 edges (kit Soft), 01 synth59 (**busy** proved single-flight vs stale pre-pin action), 03 B100, 19 AFDD flood Soft |
| Closed this cycle | Dual `fdd_run_all` OOM → **409 busy** + stale reclaim + Account Sign out (#940) · tip-completeness invalid YAML (#944) |

## Soft-OPEN (≤ Stage C)

| ID | Note |
|----|------|
| **stage-c-idp-mfa-sku** | Commercial IdP/MFA/SKU |
| **util-interval** | **CLOSED (branch)** · empty `utility_interval` view when CSV absent → UTIL-INTERVAL plans 0h (not `rules_failed`) |
| **r6-ingest-reject** | **CLOSED (branch)** · count on health + `reject_buckets` on `/api/ingest/stats` (no dead-letter dump API) |
| **kali-zap-af** | Authenticated ZAP AF remains Kali-owned |
| **wave-o1-tenant-path-migrate** | Hub-root `building=*` still; optional `tenants/{tid}/` migrate |
| **p2c-mqtt-acl-staging** | Broker ACL proof = Kali staging |
| **historian-n-building-scale** | Small Parquet parts × N buildings; offline H4 now; runtime compaction Soft later |
| **admin-capacity-gauges** | **CLOSED (branch)** · cgroup memory + workspace `statvfs` + Parquet small-file strip on Admin |
| **railway-capacity-stress** | **CITED** `20260916T215804Z` capacity_report (gates 24/24b PASS) on `sha-f318dbc` |
| **mqtt-pause-ui** | **CLOSED (branch)** · Ops edge picker + `edge:telemetry` pause/resume; stress gate `35_mqtt_telemetry_pause_resume` required on Railway + local `run_all` |
| **fdd-actions-singleflight** | **CLOSED** · live hub **3.5.26** / `sha-2c4c2d9` (#940/#943/#944) |
| **edge-kit-soft** | **OPS script** `./scripts/openfdd_restore_edge_kit.sh` → `deploy/mqtt/kits/bldg2__pi-1/` (not in git; run before fieldbus Railway up) |

## Wave R closeout (2026-09-16)

| ID | Status | Note |
|----|--------|------|
| **r1** | **CLOSED** | FC1 SQL `fan_status` parity (#936); soak ~39.58h vs golden 40 via rel-tol (#937) |
| **r2** | **CLOSED** | Wave L OFF 12–17 PASS N/A when MT ON |
| **r3** | **CLOSED** | AFDD pre-minted bearer; gate 19 PASS |
| **r4** | **CLOSED** | ZAP baseline PASS (`ACCEPT_ZAP_MEDIUM=1`) |
| **r5** | **CLOSED** | Hub pin `sha-4d3a6b0` / 3.5.22 |
| **r6** | **CLOSED (branch)** | ingest_reject count + reason buckets |
| **r7** | **CLOSED** | JCI FEC **5007** Who-Is + AI:1173 |
| **r10** | **CLOSED** | Viewer optional; Railway has `OPENFDD_VIEWER_PASSWORD` |
| **r11** | **CLOSED (branch)** | UTIL-INTERVAL empty-view parity (not FC1) |
| **r12** | Parked | Stage C |
| **r13** | **OPS PINNED** | Stress `20260916T011952Z` fully_qualified |

## Exit (P9 / R)

**Done:** tip GHCR + Railway re-pin + ONE full `run_railway_hub_stress.sh` cited + 0 open wave PRs + Soft-OPEN ≤ Stage C.
