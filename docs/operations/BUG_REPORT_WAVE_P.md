# Wave P / Wave R — Residual stress + GH tidy tracker

**Parent:** [`BUG_REPORT_WAVE_O.md`](BUG_REPORT_WAVE_O.md) Soft residuals · Wave R plan [`wave_r_stress_patches_5406b539.plan.md`](../../.cursor/plans/wave_r_stress_patches_5406b539.plan.md) · Soft UX master [`wave_ux_soft_master_a1b2c3d4.plan.md`](../../.cursor/plans/wave_ux_soft_master_a1b2c3d4.plan.md)

## Tip / GHCR / Railway

| Item | Status |
|------|--------|
| Product tip / **OPS PINNED** | **Soft Tip B `3.5.28` / `sha-4a5c11e`** (`4a5c11e5`, #947) · health `3.5.28+4a5c11e50b92` · `multi_tenant=true` · backup `20260917T214613Z` · hub stress `reports/nightly-ot-bench_20260917T215437Z/` **`fully_qualified=true`** (gates **19** + **35** PASS) · ACME fieldbus `sha-4a5c11e` · edges=`vim-1` |
| **Patch cycle 3.5.29** `2026-09-18` | **IN FLIGHT** — tip **security-harness-ship**: Python probe + gates 25/25b/26 + legacy ACL false-PASS repairs. Live execute deferred to MEGA stress (`OPENFDD_SECURITY_EXECUTE=1`). Soft-OPEN acme-oa-t + local-bacnet unchanged (DIY MS/TP@38400 available). |
| **Stability audit** `2026-09-18T00:10Z` | **No new tip** — Railway Online on `sha-4a5c11e`; SQL↔pandas oracle OK; ACME FDD `rules_failed=0` |
| **Patch cycle 3.5.29 attempt** `2026-09-18T12:00Z` | **HOLD TIP** — hygiene clean (0 open PRs, master Actions green, hub `3.5.28+4a5c11e50b92`, edges=1, ingest live). No product fix worth bump. Soft-OPEN `acme-oa-t-dup-reject` attributed to live edge **`vim-1`** (hub edges list); local `pi-1` fieldbus kit is not the registered telemetry edge. Local BACnet Soft-OPEN unchanged (FEC silence; mini MAC2 heard via `--mstp-passive` on Waveshare C). Prior FQ stress `20260917T215437Z` remains tip cite. |
| Prior tip | `3.5.27` / `sha-bf93ea7` (#946 Soft UX) · hub stress `20260917T191546Z` not FQ (19 building + 35 MT topics — fixed in Tip B) |
| Prior hub | `3.5.26` / `sha-2c4c2d9` (#944) · backup `20260917T020217Z` |
| Prior OPS PINNED | Wave R **3.5.22** / `sha-4d3a6b0` (#936) · stress `20260916T011952Z` **`fully_qualified=true`** |
| Soft Park S5 | Stress `reports/nightly-ot-bench_20260916T215804Z/` · **22 PASS / 4 FAIL** · not `fully_qualified` |
| Closed this cycle | #940 busy/sign-out · #944 tip YAML · Soft UX #946 · Tip B #947 MT `tenants/…` commands · AFDD flood building default · fieldbus Railway MT ACME identity · Soft UX master hub stress FQ · post-pin stability audit (no tip) |

## Stability audit (2026-09-18) — patch cycle decision: **hold tip**

| Check | Result |
|-------|--------|
| Railway containers | `openfdd-central-cQ-F` / `openfdd-mqtt` / `openfdd-web` **Online** · images `ghcr.io/bbartling/openfdd-*:sha-4a5c11e` · no panic/fatal in recent logs |
| Hub health | `ok` · `3.5.28+4a5c11e50b92` · `edges=1` · live `ingest_ok` · `last_ingest_at` fresh |
| ACME building | Edge `vim-1` / site `ACME` `has_telemetry=true` · `POST /api/fdd/run` building `ACME` → **`rules_succeeded=39` `rules_failed=0` `rules_skipped=29`** (statuses PASS/FAULT/SKIPPED_MISSING_ROLES/N/A only; **0 ERROR**) |
| SQL ↔ pandas | Local `sql_pandas_oracle_check.py` **OK (19 seeds)** · `golden_dual_compare.py` **OK (82 pandas fixtures)** · cookbook docs dual-catalog PASS · prior hub soak **OpenFDD SQL target match 59/59** (`01_synth59.log` in FQ stress) |
| GH tidy | **0 open PRs** · tip `4a5c11e` master workflows **success** (Publish, tip completeness, Rust/FDD CI, AppSec, …) · stale FAIL rows only on deleted Tip B feature branch (pre-fmt) — not master |
| Soft-OPEN noise | Recurring `mqtt_ingest_reject` / `historian_persist`: **`duplicate canonical live role oa_t`** (~1× per 300 s poll) from ACME stress catalog `config/fieldbus/field_devices.toml` dual AV roles on loopback 9101 — **not** a container error; cite Soft-OPEN below. Brief buffer rejects only at central redeploy. MQTT ACL world-readable warn + rare OpenSSL EOF — non-blocking. |

## Soft-OPEN (≤ Stage C)

| ID | Note |
|----|------|
| **stage-c-idp-mfa-sku** | Commercial IdP/MFA/SKU |
| **util-interval** | **CLOSED (branch)** · empty `utility_interval`/`bas_submeter` views when CSV absent → UTIL-INTERVAL plans **0h** (not `rules_failed`); pandas oracle: expect 0h when interval frame empty |
| **r6-ingest-reject** | **CLOSED (branch)** · count on health + `reject_buckets` on `/api/ingest/stats` (no dead-letter dump API) |
| **kali-zap-af** | Authenticated ZAP AF remains Kali-owned |
| **wave-o1-tenant-path-migrate** | Hub-root `building=*` still; optional `tenants/{tid}/` migrate |
| **p2c-mqtt-acl-staging** | Broker ACL proof = Kali staging |
| **historian-n-building-scale** | Small Parquet parts × N buildings; offline H4 now; runtime compaction Soft later |
| **admin-capacity-gauges** | **CLOSED (branch)** · cgroup memory + workspace `statvfs` + Parquet small-file strip on Admin |
| **railway-capacity-stress** | **CITED** Tip B FQ `20260917T215437Z` gates 24/24b PASS |
| **mqtt-pause-ui** | **CLOSED (#947 Tip B)** · MT command topics `tenants/…`; gate **35 PASS** on `sha-4a5c11e` stress `20260917T215437Z` |
| **acme-oa-t-dup-reject** | **Soft-OPEN** · ACME live `historian_persist` rejects: duplicate canonical `oa_t` in one equipment envelope. Hub `/api/edges` shows **`vim-1`** (not local `pi-1` stress catalog). Ingest still healthy (`ingest_ok` ≫ reject). Ops/edge package cleanup — not a product tip. |
| **local-bacnet-ot-bench** | **Soft-OPEN** · MS/TP/FEC shared-trunk; Waveshare C FTDI `--mstp-passive` @38400: FEC alone silence; +mini MAC2 → PFM heard. Resume when FEC online on isolated trunk. |
| **edge-kit-soft** | **OPS** · MT kit `./scripts/openfdd_restore_edge_kit.sh ACME pi-1` → `deploy/mqtt/kits/ACME__pi-1/` · live ACME OT edge id `vim-1` |

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

## Exit (P9 / R / Soft UX)

**Done:** tip GHCR + Railway re-pin + hub stress FQ (`20260917T215437Z` on `3.5.28` / `sha-4a5c11e`) + post-pin stability audit (ACME FDD clean, SQL↔pandas oracle OK, 0 open PRs, master Actions green) + Soft-OPEN ≤ Stage C (local BACnet OT bench + ACME `oa_t` dup catalog noise). **No additional product tip required for stability.**
