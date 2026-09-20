# Wave P / Wave R — Residual stress + GH tidy tracker

**Parent:** [`BUG_REPORT_WAVE_O.md`](BUG_REPORT_WAVE_O.md) Soft residuals · Wave R plan [`wave_r_stress_patches_5406b539.plan.md`](../../.cursor/plans/wave_r_stress_patches_5406b539.plan.md) · Soft UX master [`wave_ux_soft_master_a1b2c3d4.plan.md`](../../.cursor/plans/wave_ux_soft_master_a1b2c3d4.plan.md)

## Tip / GHCR / Railway

| Item | Status |
|------|--------|
| Product tip / **OPS PINNED (FQ)** | **3.5.31** / **`sha-7b81eb8`** (#951) · health `3.5.31+7b81eb810c0f` · backup `20260919T193923Z` · stress `20260919T195100Z` **`fully_qualified=true`** · live edge **`vim-1`** — **Wave S1 CLOSED** |
| Hub **smoke tip** (no FQ claim) | **3.5.33** / **`sha-3cd3745`** (#954 DM IRI v2) · health `3.5.33+3cd37451220a` · backup `20260919T231221Z` · SPARQL `/api/model/sparql` **404 unavailable** · **ACME MQTTS PASS** (`vim-1` telemetry, fresh `ingest_ok`, reject_buckets Soft-OPEN `oa_t` only) — mid-wave smoke only |
| **Stability audit** `2026-09-20T00:40Z` | Hub `3.5.33+3cd3745` · **MQTTS healthy** · edges=1 `vim-1`/ACME `has_telemetry=true` · ingest climbing after redeploy · **Soft-OPEN `acme-fdd-run-hang`**: `POST /api/fdd/run` `{building_id:ACME}` stays `running` >20m (cleared via `DELETE /api/actions`); not FQ-blocking for smoke tip; next patch cycle candidate. GH: 0 open PRs; no `tip/`/`docs/` remotes; tip Publish fieldbus in flight (hub images PASS). |
| **Wave S2** `sha-8b0eefe` / 3.5.32 | Camber lock + data-model ADR + DM-06 route matrix (#953). Smoke superseded by S5 tip pin. |
| **Wave S5 P1** `sha-3cd3745` / 3.5.33 | DM-01/02/03 IRI encoding (`enc_` reserved, `ofdd:eq_<b>__<e>`). Vitest 9/9 + Rust unit 7/7. Soft-OPEN DM-04..10 / ECM / Pages / model gate. |
| **Wave S Soft-OPEN** | Closed into **Wave T** — see Soft-OPEN rows + [`.cursor/plans/wave_t_soft-open_closeout.plan.md`](../../.cursor/plans/wave_t_soft-open_closeout.plan.md) · takeover [`TESTBED_TAKEOVER.md`](TESTBED_TAKEOVER.md) |
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
| **s1-datasets-mt-acl** | **CLOSED** (#951 / 3.5.31 / `sha-7b81eb8`) · datasets list/delete MT ACL; FQ `20260919T195100Z` gate 25/25b PASS |
| **wave-s3-pypi-mv-oracle** | **Soft-OPEN** · IPMVP change-point / G14 / Camber→`open_fdd.ecm_engineering` ports + wheel publish. Plan: `wave_s3_pypi_mv_camber_oracle.plan.md`. |
| **wave-s4-sql-twins-fq** | **Soft-OPEN** · DataFusion M&V twin + Metering UI + model/ECM gate in FQ MEGA. Plan: `wave_s4_sql_oracle_twins_fq.plan.md`. FQ cite only after this tip. |
| **wave-s5-dm-remainder** | **Soft-OPEN** · DM-04..10, SEC-ML, JSON-PARITY, SPARQL-SEM, PERF-1, EQ-VOCAB/PERSIST, ECM-ADAPT, DOCS-PAGES, STRESS-GATE. P1 IRI CLOSED on `sha-3cd3745`. |
| **acme-fdd-run-hang** | **Soft-OPEN** · On smoke tip `3.5.33`/`sha-3cd3745`, ACME `fdd_run_all` action remains `running` >20m (proxy curl timeouts; clear with `DELETE /api/actions`). MQTTS ingest unaffected. Diagnose DataFusion memory/spill / rule set before next product tip; do not greenwash. **Wave T T0.** |
| **sec-harness-mt-breadth** | **Soft-OPEN** · Grow X/Y IMPLEMENTED MT ACL/JWT coverage so Python **beats manual Burp on isolation matrices** (inventory today ~16 IMPLEMENTED / ~93 PLANNED of ~138). Not XSS/SQLi/AF — ZAP baseline + Soft-OPEN `kali-zap-af`. **Wave T T_sec.** |

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
