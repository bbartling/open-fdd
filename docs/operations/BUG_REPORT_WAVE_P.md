# Wave P / Wave R — Residual stress + GH tidy tracker

**Parent:** [`BUG_REPORT_WAVE_O.md`](BUG_REPORT_WAVE_O.md) Soft residuals · Wave R plan [`wave_r_stress_patches_5406b539.plan.md`](../../.cursor/plans/wave_r_stress_patches_5406b539.plan.md) · Soft UX master [`wave_ux_soft_master_a1b2c3d4.plan.md`](../../.cursor/plans/wave_ux_soft_master_a1b2c3d4.plan.md)

## Tip / GHCR / Railway

| Item | Status |
|------|--------|
| Product tip / **OPS PINNED (FQ)** | **3.5.31** / **`sha-7b81eb8`** (#951) · health `3.5.31+7b81eb810c0f` · backup `20260919T193923Z` · stress `20260919T195100Z` **`fully_qualified=true`** · live edge **`vim-1`** — **Wave S1 CLOSED** |
| **Wave U tip** (this PR) | **3.5.34** · security spine U0–U6 + FDD `OPENFDD_FDD_RUN_TIMEOUT_SECS` (default 900) + fieldbus fail-closed unit tests + stress catalog oa_t dedupe; smoke after GHCR — **no FQ claim** until after-spine MEGA |
| Hub smoke tip (prior) | **3.5.33** / **`sha-3cd3745`** (#954) · mid-wave smoke only |
| **Stability audit** `2026-09-20T00:40Z` | Hub `3.5.33+3cd3745` · **MQTTS healthy** · edges=1 `vim-1`/ACME `has_telemetry=true` · ingest climbing after redeploy · **Soft-OPEN `acme-fdd-run-hang`**: `POST /api/fdd/run` `{building_id:ACME}` stays `running` >20m (cleared via `DELETE /api/actions`); not FQ-blocking for smoke tip; next patch cycle candidate. GH: 0 open PRs; no `tip/`/`docs/` remotes; tip Publish fieldbus in flight (hub images PASS). |
| **Wave S2** `sha-8b0eefe` / 3.5.32 | Camber lock + data-model ADR + DM-06 route matrix (#953). Smoke superseded by S5 tip pin. |
| **Wave S5 P1** `sha-3cd3745` / 3.5.33 | DM-01/02/03 IRI encoding (`enc_` reserved, `ofdd:eq_<b>__<e>`). Vitest 9/9 + Rust unit 7/7. Soft-OPEN DM-07..10 / ECM FQ / Pages; DM-04/05 + gate 36 **PARTIAL on this tip**. |
| **Wave S Soft-OPEN** | Closed into Wave T, then **SUPERSEDED by Wave U** — [`WAVE_U_MASTER.md`](WAVE_U_MASTER.md) · takeover [`TESTBED_TAKEOVER.md`](TESTBED_TAKEOVER.md) |
| **Wave U** | **Active** — security-first spine (U0–U6); product Soft-OPEN after spine; many tiny VERSION+GHCR tips |
| **Wave S1 FQ closeout** `20260919T195100Z` | Hub `3.5.31+7b81eb810c0f` · gates 00/25/25b/35 **PASS** · `EXPECTED_EDGE_ID=vim-1` · datasets ACL fixed in #951 |
| **Wave S1 FQ fail** `20260919T152037Z` | Hub `3.5.30+471ef7ab5bde` · **`fully_qualified=false`**: wrong edge `pi-1`; `y.authz.a_foreign_datasets_denied` 200 → fixed 3.5.31 |
| **Wave S1 audit** `2026-09-19` | Suite expand #950 / `471ef7a` / 3.5.30; Soft-OPEN `acme-oa-t-dup-reject` unchanged |
| Prior Soft Tip B | **3.5.28** / `sha-4a5c11e` · stress `20260917T215437Z` **`fully_qualified=true`** |
| **Patch cycle 3.5.29** `2026-09-18` | Merged #948 → GHCR tip PASS → Railway backup+re-pin → fieldbus ACME → MEGA FQ. Soft-OPEN acme-oa-t + local-bacnet unchanged. Follow-on PR: stress QUAL/`set -u` order, Railway security fixtures, ZAP Medium dispositions, gate 25b login 429 reuse. |
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
| Soft-OPEN noise | Stress catalog `field_devices.toml` dual `oa_t` on AV 9101 **removed** in 3.5.34 tip (`acme-oa-t-dup-reject` CLOSED for repo catalog). Live `vim-1` kit may still need restore/redeploy before hub rejects stop. Brief buffer rejects only at central redeploy. |

## Soft-OPEN (≤ Stage C)

| ID | Note |
|----|------|
| **stage-c-idp-mfa-sku** | Commercial IdP/MFA/SKU |
| **util-interval** | **CLOSED (branch)** · empty `utility_interval`/`bas_submeter` views when CSV absent → UTIL-INTERVAL plans **0h** (not `rules_failed`); pandas oracle: expect 0h when interval frame empty |
| **r6-ingest-reject** | **CLOSED (branch)** · count on health + `reject_buckets` on `/api/ingest/stats` (no dead-letter dump API) |
| **kali-zap-af** | **→ Wave U U5** `zap-af-authenticated` · runner + selftest landed; Soft-OPEN until disposable EXECUTE High=0 |
| **wave-o1-tenant-path-migrate** | Hub-root `building=*` still; optional `tenants/{tid}/` migrate |
| **p2c-mqtt-acl-staging** | **CLOSED** (folded into `mqtt-key-mode-tenant-acl`) · synthetic A/B tenant ACL fixture + observer covers P2c matrix (own write / foreign deny / no edge wildcards) |
| **historian-n-building-scale** | Small Parquet parts × N buildings; offline H4 now; runtime compaction Soft later |
| **admin-capacity-gauges** | **CLOSED (branch)** · cgroup memory + workspace `statvfs` + Parquet small-file strip on Admin |
| **railway-capacity-stress** | **CITED** Tip B FQ `20260917T215437Z` gates 24/24b PASS |
| **mqtt-pause-ui** | **CLOSED (#947 Tip B)** · MT command topics `tenants/…`; gate **35 PASS** on `sha-4a5c11e` stress `20260917T215437Z` |
| **acme-oa-t-dup-reject** | **CLOSED (catalog 3.5.34)** · `config/fieldbus/field_devices.toml`: zone loopback no longer maps `outside-air-temperature` on AV 9101; `hosted-weather` owns `web-outside-air-temp`. Live `vim-1` needs kit restore to clear residual hub rejects. |
| **local-bacnet-ot-bench** | **Soft-OPEN** · MS/TP/FEC shared-trunk; Waveshare C FTDI `--mstp-passive` @38400: FEC alone silence; +mini MAC2 → PFM heard. Resume when FEC online on isolated trunk. |
| **edge-kit-soft** | **OPS** · MT kit `./scripts/openfdd_restore_edge_kit.sh ACME pi-1` → `deploy/mqtt/kits/ACME__pi-1/` · live ACME OT edge id `vim-1` |
| **s1-datasets-mt-acl** | **CLOSED** (#951 / 3.5.31 / `sha-7b81eb8`) · datasets list/delete MT ACL; FQ `20260919T195100Z` gate 25/25b PASS |
| **wave-s3-pypi-mv-oracle** | **PARTIAL (branch tip/wave-u-u0-master)** · IPMVP change-point (`2P`/`3P`/`4P`/`5P`) + G14 NMBE/CVRMSE in `open_fdd.ecm_engineering` (+ analytics re-exports) · cookbook [`docs/ecm/ipmvp-changepoint.md`](../ecm/ipmvp-changepoint.md) · wheel `4.4.3` local build/test · **Soft-OPEN residual:** PyPI publish tip, unfinished Camber families, Wave S4 SQL twin / Metering UI. Plan: `wave_s3_pypi_mv_camber_oracle.plan.md`. |
| **wave-s4-sql-twins-fq** | **Soft-OPEN (tip prep)** · Thin `POST /api/analytics/mv` (`mv-change-point-v1` 2P OLS) + Metering M&V radio + gate **36** (`scripts/nightly-ot-bench/36_mv_sql_oracle_twin.sh`). Default gate **BLOCKED** without `OPENFDD_SECURITY_EXECUTE=1`. **Do not claim OPS PINNED / FQ PASS** until tip merge + GHCR + MEGA FQ with EXECUTE=1. Plan: `wave_s4_sql_oracle_twins_fq.plan.md`. |
| **wave-s5-dm-remainder** | **PARTIAL (this tip)** · DM-04 stamped types + inferred-parent honesty + DM-05 tenant storage doc + gate **36** model/ECM wire. Soft-OPEN remains: DM-07..10 SPARQL/PERF, EQ-VOCAB/ECM-ADAPT FQ, Pages publish soak. P1 IRI still CLOSED on `sha-3cd3745`. |
| **acme-fdd-run-hang** | **CLOSED (3.5.34)** · Stale `running` reclaim **20m** + `list_actions` reclaim + `POST /api/fdd/run` wall timeout via `OPENFDD_FDD_RUN_TIMEOUT_SECS` (default **900s**) finishes action `fail`/`timeout` instead of indefinite hang. Slow ACME DataFusion remains a performance topic, not an action hang. |
| **sec-harness-mt-breadth** | **PARTIAL (this tip)** · Expanded Y/X: mapping TTL foreign deny + FDD equipment own/foreign; inventory IMPLEMENTED honest. Soft-OPEN: more PLANNED MT routes (analytics POSTs, series, buildings list, …). |
| **sec-harness-evaluator-integrity** | **CLOSED (3.5.34)** · E01–E08 permanent tests + fixes |
| **sec-ci-wire** | **CLOSED (3.5.34)** · AppSec `security-harness` job |
| **standalone-https-bootstrap** | **CLOSED (3.5.34)** · compose + Caddyfile HTTP→HTTPS redir; CI `peer_probe_https.py --selftest`; peer soak PASS `2026-09-20T15:01:25Z` → `reports/security/standalone_https_probe.json` (not Nessus) |
| **fieldbus-mgmt-failclosed** | **CLOSED (3.5.34)** · `require_api_key_for_bind` + unit tests (`non_loopback_without_key_refused`, loopback/key cases) |
| **mqtt-key-mode-tenant-acl** | **CLOSED** · key mode 640 (`docker-entrypoint-openfdd.sh`) + generated fixture `scripts/security/fixtures/mqtt_tenant_acl/` + observer `scripts/security/mqtt_tenant_acl_observer.py` · gate `26_security_mqtt_acl` PASS when `OPENFDD_MQTT_ACL_EXECUTE=1` · folds `p2c-mqtt-acl-staging` |
| **zap-af-authenticated** | **Soft-OPEN / BLOCKED** · `scripts/qualification/zap/run_af_disposable.sh` + unit tests; `--selftest` proves plan hygiene + verdict schema and exits **BLOCKED** (not PASS). Real PASS only with `OPENFDD_ZAP_AF_EXECUTE=1` + `ZAP_TARGET_ORIGIN` + `ZAP_AUTH_HEADER_VALUE` against disposable target and High=0 — no fake High=0 without a scan. |
| **image-digest-trivy** | **TIPPED 3.5.34** · `trivy_ghcr_digests.sh` (run after GHCR publish) |
| **nessus-pass-readiness** | **CLOSED (3.5.34)** · checklist + importer + fixtures + HTTPS/MQTT/fieldbus evidence cited — **not** a fake Nessus PASS; real scan remains `nessus-isolated-assessment` BLOCKED |
| **nessus-isolated-assessment** | **Soft-OPEN / BLOCKED** · Real licensed Nessus only |

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
