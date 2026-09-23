# Wave P / Wave R — Residual stress + GH tidy tracker

**Parent:** [`BUG_REPORT_WAVE_O.md`](BUG_REPORT_WAVE_O.md) Soft residuals · Wave R plan [`wave_r_stress_patches_5406b539.plan.md`](../../.cursor/plans/wave_r_stress_patches_5406b539.plan.md) · Soft UX master [`wave_ux_soft_master_a1b2c3d4.plan.md`](../../.cursor/plans/wave_ux_soft_master_a1b2c3d4.plan.md)

## Tip / GHCR / Railway

| Item | Status |
|------|--------|
| Product tip / **OPS PINNED (FQ)** | **3.5.43** / **`sha-7ad6479`** (#978) · health `3.5.43+7ad6479c924a` · backup **`20260921T233725Z`** · stress `reports/nightly-ot-bench_20260921T234148Z/` **`fully_qualified=true`** · live edge **`vim-1`** — **Wave U V6 FQ** |
| **W7 MEGA FAIL (not OPS PINNED)** | Hub tip **3.5.47** / **`sha-cc23e89`** · MEGA `reports/nightly-ot-bench_20260923T035138Z/` `fully_qualified=false` — sensor-health **CLOSED** (HTTP 200); residual FAIL **25** foreign `rcx/ahu` TimeoutError + **37** `analytics/runtime` **502** (unbounded LEAD fallback) · tip **3.5.48–3.5.50** seatbelts · OPS still `sha-7ad6479` / 3.5.43 until ACME AFDD qual MEGA |
| **Follow-on tip (not OPS PINNED)** | Master tip **3.5.50** / **`sha-3e6048e`** (#994) · next tip **ACME AFDD 24h qual** · OPS still `sha-7ad6479` / 3.5.43 until FQ |
| **ACME AFDD professional** `2026-09-23` | Compaction APPLY `reports/wave_u_acme_compaction_apply_20260923T125014Z/` — **54814→0** eligible parts; `OPENFDD_PARQUET_FLUSH_SECONDS=300`. Soft-OPEN: continuous AFDD still **off** until hub pin + gate 38 MEGA. |
| **Wave U post-FQ remainder** `2026-09-22` | Master W-UI→W0–W7 · ECM [ecm_context_hardening.plan.md](../../.cursor/plans/ecm_context_hardening.plan.md) · V1–V8 scheduling **SUPERSEDED** |
| **Wave U remainder cycles** `2026-09-21` | **SUPERSEDED** [wave_u_remainder_patch_cycles.plan.md](../../.cursor/plans/wave_u_remainder_patch_cycles.plan.md) · historical V1–V8 only |
| **Wave U hub tip (smoke + MEGA in flight)** | **3.5.34** / **`sha-f44b45f`** (#959) · health `3.5.34+f44b45f6f58d` · backup **`20260920T193429Z`** · fieldbus `OPENFDD_RAILWAY_EDGE_ID=vim-1` kit restored · MEGA `reports/nightly-ot-bench_20260920T194610Z/` · **no FQ / OPS PINNED claim until `fully_qualified=true`** |
| Hub smoke tip (prior) | **3.5.33** / **`sha-3cd3745`** (#954) · mid-wave smoke only · superseded by `sha-f44b45f` re-pin |
| **Wave U FQ closeout notes** `2026-09-20` | H0: required Actions green on `f44b45f`; Optional BACnet FAIL = fail-closed without CI key → **#960 FIXED** (`bacnet-mqtt-e2e` PASS). H1: #958 HOLD (baud docs); `tip/wave-u-u0-master` deleted; only `docs/diy-baud-hold-ai-context` remote. P1: `check_ghcr_tip_stack sha-f44b45f` PASS; Trivy cite `reports/trivy-wave-u/sha-f44b45f/SUMMARY.md` (mqtt 0; Debian/Alpine OS High residual — not greenwashed). Smoke: `POST /api/analytics/mv` **200** (clears `wu-mv-404-pre-pin`); edges=1 `vim-1` telemetry; ingest climbing (residual `ingest_reject` post kit restore). |
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
| **Wave U hub tip (superseded)** | **3.5.36** / **`sha-812bd92`** (#962) · health `3.5.36+812bd925bab3` · backup **`20260920T230554Z`** · fieldbus `vim-1` · MEGA `reports/nightly-ot-bench_20260920T231407Z/` · **`fully_qualified=false`** (logged before tip fix) |
| **#962 merged** | **3.5.36** independent acceptance UA evaluators + HTTPS/field keys/ZAP hygiene |
| **#961 merged** | **3.5.35** `e23c9ac` — rcx presets building ACL · gate26 verdict · OPS password aliases · MT edge CN uses tenant_id |
| **#962 tip** | **3.5.36** `tip/wave-u-acceptance-ua` — UA evaluator gates + HTTPS compose; follow-on: key mode 0600, field-only exposure, host/runtime selftest, web Alpine base bump, isolated FALLBACK `sha-f44b45f` |
| **Wave U independent acceptance** `2026-09-20` | Audit UA-01..10 **REOPENED** insufficient Soft-OPEN closes. Permanent negatives for 14 false-pass evaluators landed on tip (identity `tenant_ids`, ZAP AF fail-closed, MQTT require-live, Nessus per-host completeness, both gate **36** required + railway_field provenance). Offline audit reproducer **false_pass=0**. **Not VERIFIED / not OPS PINNED** until green CI → GHCR tip → candidate MEGA. Nessus licensed assessment remains BLOCKED. |
| **UA-05 images** | **W1 tip rescan** `reports/trivy-wave-u/sha-7ad6479/SUMMARY.md` — web nginx **cleared** (0 H/C, `1.28.3-r7`); mqtt 0; Debian/caddy TRACKED — [`IMAGE_FINDING_DISPOSITIONS.md`](IMAGE_FINDING_DISPOSITIONS.md) |
| **UA-08 field/host** | Tip adds provisioner `0600` keys + dual-tenant isolation tests; MQTT entrypoint fail-closed on insecure key mode; `field_only_ot` exposure + `compose.edge` lint; `host_runtime_probe.py` selftest |

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
| **kali-zap-af** | **CLOSED (UA-04 / W2)** · alias of `zap-af-authenticated` — disposable AF PASS `reports/security/zap_af_disposable_20260922T151322Z/` |
| **wave-o1-tenant-path-migrate** | **CLOSED (3.5.41 / V7 + W5 live)** · Dual-read prefers `tenants/{tid}/…` then hub-root; migrate script additive. Live hub dry-run `reports/wave_u_v7_tenant_path_migrate_hub_20260922T185532Z/` — ACME/BUILDING_100/LAKESIDE_ES already `skip_already_migrated` (eq counts match); dual-read smoke `GET /api/tenants` + `GET /api/fdd/equipment` (49 / 71). APPLY noop — no `CONFIRM_BACKUP` copy needed. |
| **p2c-mqtt-acl-staging** | **REOPENED acceptance (UA-03)** · folded into `mqtt-key-mode-tenant-acl`; product-generated runtime ACL matrix still required — **V2** |
| **historian-n-building-scale** | **CLOSED (V8 + W5 live soak)** · H4 + `CompactionCoordinator` + hub-admin `GET\|POST /api/historian/compaction`. Live soak `reports/wave_u_v8_compaction_soak_20260922T185707Z/` on hub `3.5.43+7ad6479`: fail-closed no-confirm **HTTP 400**; `plan_only` + `confirm:true wait:true` **ok** with **0** eligible hive partitions (equipment trees are single-file — honest empty compact, not a silent skip of the API). Soft residual: multi-part hive compact only when parts accumulate. |
| **w7-acme-tenant-history-fanout** | **CLOSED (APPLY 20260923T125014Z)** · Was ~54.8k tiny parts; hub-admin compaction APPLY collapsed to eligible plans=0 (~1.6 MiB outputs). Alias of acme-parquet-fanout. Flush coalesce `OPENFDD_PARQUET_FLUSH_SECONDS=300`. |
| **acme-parquet-fanout** | **CLOSED (APPLY)** · See `reports/wave_u_acme_compaction_apply_20260923T125014Z/SOAK_SUMMARY.md`. |
| **acme-afdd-continuous-off** | **PARTIAL** · Env now `continuous`/1440/24h/ACME on hub `sha-f885fe4` (scheduler status matches). Soft residual: tip #995 memory wire + `timer_scope` + gate 38 **NOT RUN** on tip digest; timer continuity **NOT RUN** (`recent_cycles=[]`). Resource validation: `reports/railway_afdd_resource_validation_20260923T131500Z/`. |
| **wu-query-memory-unenforced** | **OPEN (tip fix in flight)** · Deployed analytics/AFDD used bare `SessionContext::new()` — `OPENFDD_QUERY_MEMORY_MB=512` **not honored** until #995 bounded-session wire lands + re-pin. |
| **wu-analytics-http200-failclosed** | **OPEN (harness)** · Gate 37 now FAILs `coverage.fail_closed` / timeout envelopes; live runtime smoke on `sha-f885fe4` → **HAS_ROWS** (n=38), not fail-closed. |
| **admin-capacity-gauges** | **CLOSED (branch)** · cgroup memory + workspace `statvfs` + Parquet small-file strip on Admin |
| **railway-capacity-stress** | **CITED** Tip B FQ `20260917T215437Z` gates 24/24b PASS |
| **mqtt-pause-ui** | **CLOSED (#947 Tip B)** · MT command topics `tenants/…`; gate **35 PASS** on `sha-4a5c11e` stress `20260917T215437Z` |
| **w7-mega-20260922T213831Z** | **Soft-OPEN / FAIL** · MEGA on `sha-9da9902` / 3.5.45 · `fully_qualified=false` — see section below; tip **3.5.46** site_id + **3.5.47** sensor-health |
| **w7-mega-20260923T004400Z** | **HISTORICAL almost FQ** · 3.5.46 · residual was sensor-health → closed on 3.5.47 |
| **w7-gate35-pick-edge-lab** | **CLOSED (re-MEGA PASS)** · Gate 35 PASS on `20260923T004400Z` after `resolve_edge_target` + `registered_site_id` tip |
| **w7-list-edges-site-id** | **CLOSED (re-MEGA PASS)** · `list_edges` site_id retained; gate 35 PASS on tip `sha-5660837` |
| **w7-gate25-analytics-timeout** | **Soft-OPEN → residual product** · harness settle helped foreign 403; own `y.authz.a_own_analytics_sensor_health` still **502** on unbounded UNION ALL — tip **3.5.47** lookback |
| **w7-gate25-sensor-health-502** | **CLOSED (3.5.47 / sha-cc23e89)** · Idle + MEGA own sensor-health **HTTP 200**; Soft-OPEN closed for product path |
| **w7-mega-20260923T035138Z** | **Soft-OPEN / FAIL** · MEGA on `sha-cc23e89` / 3.5.47 · sensor-health PASS; FAIL **25** foreign rcx/ahu TimeoutError + **37** analytics/runtime **502**; **26** BLOCKED (MEGA ran stale local harness without auto `MQTT_ACL_EXECUTE`) — tip **3.5.48** |
| **w7-gate37-runtime-502** | **CLOSED (3.5.48 / sha-7a0e34e)** · Idle + MEGA `analytics/runtime` HTTP 200 (~13s) |
| **w7-gate37-mech-cooling** | **Soft-OPEN (patched tip)** · 14d lookback + SQL timeout landed 3.5.49; **3.5.50** walls entire scan+query (ACME 54k parts stall `open_history_scoped`); Soft-OPEN until re-MEGA |
| **w7-mega-20260923T061852Z** | **Soft-OPEN / FAIL** · MEGA on `sha-7a0e34e` / 3.5.48 · 25/26/35 PASS; FAIL synth59 fixtures (worktree), 25b boiler-health 502 + foreign timeouts, 37 mechanical_cooling hang — tip **3.5.49** |
| **w7-gate25-foreign-rcx-timeout** | **Soft-OPEN / harness** · foreign `/api/analytics/rcx/ahu` TimeoutError under post-capacity pressure; timeout default **45s** + settle; Soft-OPEN until re-MEGA |
| **w7-gate37-analytics-502** | **CLOSED (re-MEGA PASS)** · Gate 37 PASS on `20260923T004400Z` |
| **w7-gate26-acl-execute** | **CLOSED (re-MEGA PASS)** · Gate 26 PASS on `20260923T004400Z` (auto `OPENFDD_MQTT_ACL_EXECUTE=1`) |
| **acme-oa-t-dup-reject** | **CLOSED (catalog 3.5.34)** · `config/fieldbus/field_devices.toml`: zone loopback no longer maps `outside-air-temperature` on AV 9101; `hosted-weather` owns `web-outside-air-temp`. Live `vim-1` needs kit restore to clear residual hub rejects. |
| **local-bacnet-ot-bench** | **Soft-OPEN** · MS/TP/FEC shared-trunk; Waveshare C FTDI `--mstp-passive` @38400: FEC alone silence; +mini MAC2 → PFM heard. Resume when FEC online on isolated trunk. |
| **edge-kit-soft** | **OPS** · MT kit `./scripts/openfdd_restore_edge_kit.sh ACME pi-1` → `deploy/mqtt/kits/ACME__pi-1/` · live ACME OT edge id `vim-1` |
| **s1-datasets-mt-acl** | **CLOSED** (#951 / 3.5.31 / `sha-7b81eb8`) · datasets list/delete MT ACL; FQ `20260919T195100Z` gate 25/25b PASS |
| **wave-s3-pypi-mv-oracle** | **CLOSED (PyPI)** · `open-fdd==4.4.3` live; tip **4.4.4** adds `ecm_context_v1` envelope (W4 / [ecm_context_hardening.plan.md](../../.cursor/plans/ecm_context_hardening.plan.md)) |
| **wu-pypi-publish-4.4.3** | **CLOSED** · verified PyPI 4.4.3 live 2026-09-22 |
| **wave-s5-dm-remainder** | **PARTIAL (W4)** · EQ-VOCAB + ECM-ADAPT + DM-10 narrow + Pages CLOSED (4.4.7 / 3.5.45); Soft-OPEN residual **DM-09/PERF-1 scale RSS** · **EQ-PERSIST** · ECM REST/MCP |
| **wave-s4-sql-twins-fq** | **CLOSED (FQ)** · MEGA `20260921T021332Z` `fully_qualified=true` on `sha-1677c33` / 3.5.37 · both gate 36 PASS · OPS PINNED |
| **acme-fdd-run-hang** | **CLOSED (3.5.34)** · Stale `running` reclaim **20m** + `list_actions` reclaim + `POST /api/fdd/run` wall timeout via `OPENFDD_FDD_RUN_TIMEOUT_SECS` (default **900s**) finishes action `fail`/`timeout` instead of indefinite hang. Slow ACME DataFusion remains a performance topic, not an action hang. |
| **sec-harness-mt-breadth** | **ADVANCED (W2 #982)** · +6 plant/zone health routes IMPLEMENTED (boiler/chiller/CT/HP/zone/sensor); residual PLANNED remain · [wave_u_post-fq_remainder.plan.md](../../.cursor/plans/wave_u_post-fq_remainder.plan.md) |
| **sec-harness-evaluator-integrity** | **CLOSED for UA-01/03/04/06/07 contract (tip)** · Permanent negatives + MEGA required gates; Soft-OPEN remains for breadth (MT routes) and product MQTT image vs fixture broker |
| **sec-ci-wire** | **CLOSED (3.5.34)** · AppSec `security-harness` job |
| **standalone-https-bootstrap** | **candidate PASS (UA-02 / W1)** · Product soak `reports/security/standalone_https_peer_20260922T152529Z` on `sha-7ad6479` / 3.5.43 (trusted CA + HTTP→HTTPS); prior `…134930Z` on `sha-af4086f`; stub peer retained as component |
| **fieldbus-mgmt-failclosed** | **CLOSED (3.5.34)** · `require_api_key_for_bind` + unit tests (`non_loopback_without_key_refused`, loopback/key cases) |
| **mqtt-key-mode-tenant-acl** | **PARTIAL→product live PASS (UA-03)** · Gate/observer default `openfdd-mqtt` + provisioner ACL; tip live PASS on `sha-af4086f`; fixture broker requires ALLOW_FIXTURE — **V2** |
| **zap-af-authenticated** | **CLOSED (UA-04 / W2)** · disposable AF PASS `reports/security/zap_af_disposable_20260922T151322Z/` (`auth_me_hit`, High=0/Medium=0); plan seeds `/api/health` (#982) |
| **image-digest-trivy** | **PARTIAL (UA-05 / W1)** · Tip rescan `sha-7ad6479`: web nginx H/C **0/0**; mqtt **0**; Debian central/fieldbus/mcp + caddy TRACKED UNFIXED — not readiness VERIFIED |
| **agent-report-chart-parity** | **OPEN (W-CHART)** · PyPI/Typst agent PDF charts vs React Plotly one-for-one (colors/axes/scatter) — [agent_report_chart_parity.plan.md](../../.cursor/plans/agent_report_chart_parity.plan.md) |
| **nessus-pass-readiness** | **PARTIAL (UA-08/09)** · host_runtime_probe PASS `reports/security/host_runtime_probe_v3.json` (field_only_ot) + field-only lint; Nessus still BLOCKED |
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

## Independent acceptance review — 2026-09-20

Scope: source head `dc808c8acb315ca9feada97faa21b65ba7773d0f` and PR #959–#961 trail, reviewed while #961 was in flight. Existing suites rerun: **55 security + 16 qualification tests PASS**. Additional synthetic evaluator checks found **14 false qualifications**. This is an audit of acceptance behavior, not a live penetration test or a Nessus scan. Source hashes and synthetic reproductions are retained in the private audit workspace; detailed local handoff: `.cursor/plans/wave_u_independent_acceptance_audit.plan.md`.

The current closure rows above are corrected prospectively. Earlier scan/test acquisitions and failed stress attempts remain historical facts. [MILESTONES.md](../../MILESTONES.md) separates implementation, verification and release. No licensed scanner is needed to complete readiness work; the actual licensed assessment remains BLOCKED.

| Bug / audit ID | Priority | Status | Required acceptance / owner |
| --- | --- | --- | --- |
| `wu-audit-ua01-qualification` | P1 | FIXED (contract) | Both gate 36 required + provenance; MEGA `20260921T021332Z` FQ |
| `wu-audit-ua02-standalone` | P1 | PARTIAL→evidence PASS | Product candidate soak PASS `standalone_https_peer_20260922T152529Z` on `sha-7ad6479`; compose hide web:3000 retained; Soft-OPEN only if acceptance still requires newer tip |
| `wu-audit-ua03-mqtt` | P1 | PARTIAL | require-live + gate 26 PASS on tip; product MQTT image vs eclipse-mosquitto fixture still Soft-OPEN |
| `wu-audit-ua04-zap` | P1 | **CLOSED (W2)** | Disposable AF PASS `zap_af_disposable_20260922T151322Z` (`auth_me_hit`, High=0) |
| `wu-audit-ua05-images` | P1 | PARTIAL | W1 tip rescan `sha-7ad6479` — nginx cleared; Debian/caddy residual OPEN |
| `wu-audit-ua06-importer` | P1 | FIXED (code) / assessment BLOCKED | Per-host credentialed/completeness validation + permanent negatives on tip; licensed scan still BLOCKED |
| `wu-audit-ua07-identity` | P1 | FIXED (code) | `tenant_ids` membership enforcement + permanent negatives on tip; broader MT route matrix remains Soft-OPEN |
| `wu-audit-ua08-field-host` | P1 | PARTIAL | Key `0600`, dual-tenant kits, field-only exposure, host selftest on tip; live host probe + runtime container evidence still required |
| `wu-audit-ua09-readiness-scope` | P1 | DOCS CORRECTED / VERIFICATION OPEN | Release maintainer: license-free readiness retained as required; close only after measured profile evidence |
| `wu-audit-ua10-product-closeout` | P2 | PARTIAL | RCx presets ACL + hub FQ twins CLOSED; Soft-OPEN: S5 DM-09 scale PERF + EQ-PERSIST / ECM REST (EQ/ECM/DM-10 narrow closed on W4), MT breadth |
| `wu-bacnet-ci-ro-key-mode` | CI | **FIXED (#966)** | Smoke stages keys 640; broker cert mount writable for mosquitto chown; e2e PASS on tip |
| `wu-s4-fq-mega` | Soft-OPEN | **CLOSED** | MEGA `20260921T021332Z` `fully_qualified=true` → OPS PINNED `sha-1677c33` / 3.5.37 |
| `wu-trivy-tip-digest` | Soft-OPEN | **W1 RESCANED** | `reports/trivy-wave-u/sha-7ad6479/SUMMARY.md` — web nginx cleared; Debian/caddy remain; 3.5.44 GHCR lag |

**Do not claim:** Nessus assessment PASS · readiness VERIFIED while Critical/High unresolved · Soft-OPEN CLOSED without measured evidence. |

For each fix append candidate/harness SHA, image/config/fixture hashes, profile, actual CI/run/artifact references, expected/observed outcomes and retest result. Do not mark these rows FIXED merely because a plan or test file was added. These owner labels identify responsibility; assign an actual maintainer when scheduling.



## Wave U W7 MEGA attempt `20260922T213831Z` — **FAIL** (not OPS PINNED)

**Tip under test:** `sha-9da9902` / `3.5.45+9da9902` · backup `20260922T213028Z` · edge `vim-1` · EXECUTE=1 · **`OPENFDD_MQTT_ACL_EXECUTE` unset**  
**Artifact:** `reports/nightly-ot-bench_20260922T213831Z/` · **`fully_qualified=false`**

| Gate | Result | Root cause |
|------|--------|------------|
| **35 pause/resume** | **FAIL** | Harness `pick_edge`: edges JSON had `vim-1` with `has_telemetry:false` and **no `site_id`** → silent fallback `OPENFDD_SITE_ID=lab` from `bench.env.example`. Command → `…/buildings/lab/edges/vim-1/commands/…` while fieldbus subscribes `…/buildings/ACME/…`. Evidence: `cmd_suspend.json` `site_id: lab`; live edges later show `site_id: ACME`. Product: `list_edges` only emits site from `last_telemetry`. |
| **25 security python** | **FAIL** | 4× `TimeoutError` on foreign analytics authz POSTs (`ahu-health` / `vav-health` / `rcx/ahu` / `sensor-health`) at 10s transport budget. Same endpoints return **403 in ~300ms** when hub idle → overload under concurrent stress, not wrong ACL. |
| **37 ACME analytics** | **FAIL** | `POST /api/analytics/runtime` HTTP **502** (~35s) under load after capacity/AFDD; idle probe **200** with data. |
| **25b** | **BLOCKED** | Downstream of gate 25 errors. |
| **26 MQTT ACL** | **BLOCKED** | `OPENFDD_MQTT_ACL_EXECUTE!=1` (prior FQ MEGA set it; this run did not auto-enable). |

**Follow-up tip `3.5.46`:** product `list_edges` retains registered MQTT topic `site_id`; harness `pick_edge` prefers `EXPECTED_SITE_ID` / fail-closed (never silent `lab`); auto `OPENFDD_MQTT_ACL_EXECUTE=1` when `OPENFDD_SECURITY_EXECUTE=1`; settle + foreign-analytics timeout bump; gate 37 one 502 retry after settle.

## Wave U W7 re-MEGA `20260923T004400Z` — **almost FQ** (not OPS PINNED)

**Tip under test:** `sha-5660837` / `3.5.46` · site_id + harness tip live · `OPENFDD_QUERY_MEMORY_MB=512`  
**Artifact:** `reports/nightly-ot-bench_20260923T004400Z/` · gates **35/37/26 PASS** · residual FAIL gate **25**

| Gate | Result | Root cause |
|------|--------|------------|
| **35 / 37 / 26** | **PASS** | site_id Soft-OPEN closed for this run |
| **25 security python** | **FAIL** | `y.authz.a_own_analytics_sensor_health` observed **502** (~41s Railway `Application failed to respond`). Idle probe same. ACME `tenants/acme/history/` ~54k tiny parts; `sensor_health_from_history` built **UNION ALL** of ~40 role aggregates over **full history** (no time window) → hang/OOM. |
| **25b** | **BLOCKED** | Foreign sensor-health `TimeoutError` downstream of own 502 |

**Follow-up tip `3.5.47` (this PR):** default **14-day** `timestamp_utc` lookback (honor `query.start`/`end`); single-pass GROUP BY role aggregates (no N×UNION ALL); 30s fail-closed empty envelope; ParquetCompactor/stats list `tenants/*/history`. **Do not claim FIXED Soft-OPEN until re-MEGA `fully_qualified=true`.**

## Wave U MEGA FQ attempt `20260921T021332Z` — **PASS / OPS PINNED**

**Tip:** `sha-1677c33` / `3.5.37+1677c33047bd` · backup `20260921T013819Z` · edge `vim-1` · EXECUTE=1 · `OPENFDD_MQTT_ACL_EXECUTE=1` · `OPENFDD_IMAGE_TAG`/`OPENFDD_MCP_IMAGE=sha-1677c33`  
**Artifact:** `reports/nightly-ot-bench_20260921T021332Z/` · **`fully_qualified=true`**

Prior FAILs `20260920T194610Z` / `20260920T231407Z` / `20260921T014908Z` retained. Security 25/25b/26 PASS; both gate 36 PASS; 35 PASS after tip pin preserve.

## Wave U MEGA FQ attempt `20260921T014908Z` — **FAIL** (not OPS PINNED)

**Tip under test:** `sha-1677c33` / `3.5.37+1677c33047bd` · backup `20260921T013819Z` · edge `vim-1` · EXECUTE=1 · `OPENFDD_MQTT_ACL_EXECUTE=1`  
**Artifact:** `reports/nightly-ot-bench_20260921T014908Z/` · `fully_qualified=false`

| Gate | Result | Root cause |
|------|--------|------------|
| 25 / 25b / **26** / **both 36** | **PASS** | Viewer `OPENFDD_VIEWER_TENANT_IDS=acme` + MQTT ACL execute alias fixed |
| **08 MCP** | **FAIL** | Sticky repo `.env` `OPENFDD_IMAGE_TAG=sha-c1b1aa5` clobbered tip before `RAILWAY_ONLY` restore |
| **35 pause/resume** | **FAIL** | MQTT ack `executed` but local fieldbus `suspended=false` (REST suspend works) — likely command path / timing under tip |

**Follow-up:** set `RAILWAY_ONLY=1` before `load_bench_env`; refresh local `.env` tip; re-stress after login rate-limit cool-down.

## Wave U MEGA FQ attempt `20260920T231407Z` — **FAIL** (not OPS PINNED)

**Tip under test:** `sha-812bd92` / `3.5.36+812bd925bab3` · backup `20260920T230554Z` · edge `vim-1` · EXECUTE=1 · `MQTT_ACL_EXECUTE` alias (missed `OPENFDD_` prefix) · ACCEPT_ZAP_MEDIUM=1  
**Artifact:** `reports/nightly-ot-bench_20260920T231407Z/` · `fully_qualified=false`

| Gate | Result | Root cause |
|------|--------|------------|
| 00–07, 09–24, **35**, **both 36** | **PASS** | Pause/resume OK after ACL/CN tip; MV + model/ECM both PASS on repaired contract |
| **08 MCP** | **FAIL** | Derived MCP tip `sha-c1b1aa5` missing; `sha-812bd92` MCP exists — pin/`OPENFDD_IMAGE_TAG` derive fix |
| **25 / 25b** | **FAIL** | `y.authz._login_viewer` expected `tenant_ids=['acme']` got `[]` — env viewer login empty membership |
| **26 MQTT ACL** | **BLOCKED→FAIL** | Gate requires `OPENFDD_MQTT_ACL_EXECUTE=1`; alias + BLOCKED `security_gate_verdict.json` in tip 3.5.37 |

**Follow-up tip `3.5.37`:** `OPENFDD_VIEWER_TENANT_IDS` · MCP tip from `OPENFDD_IMAGE_TAG` / shortsha · MQTT ACL execute alias + BLOCKED verdict file · Railway set `OPENFDD_VIEWER_TENANT_IDS=acme`.

## Wave U MEGA FQ attempt `20260920T194610Z` — **FAIL** (not OPS PINNED)

**Tip under test:** `sha-f44b45f` / `3.5.34+f44b45f6f58d` · backup `20260920T193429Z` · edge `vim-1` · EXECUTE=1 · MQTT_ACL_EXECUTE=1 · ACCEPT_ZAP_MEDIUM=1  
**Artifact:** `reports/nightly-ot-bench_20260920T194610Z/` · `fully_qualified=false`

| Gate | Result | Root cause |
|------|--------|------------|
| 00–24, 36 MV twin | **PASS** (12–17 N/A MT) | MV `api_compared` path live after re-pin |
| **25 / 25b** | **FAIL** | `y.authz.a_foreign_analytics_rcx_presets_denied` observed **200** — static presets list ignored building ACL |
| **26** | **ERROR** | Observer **PASS** but missing `security_gate_verdict.json` (script wrote `mqtt_acl_verdict.json` only) |
| **35** | **FAIL** | Command `published:true` but no ack / `suspended=false` — (1) Railway MQTT ACL `central:bldg2` lacked `tenants/+/…/commands/#` write (patched live + HUP); (2) kit CN `edge:ACME:vim-1` ≠ ACL `edge:acme:vim-1` — commands never delivered (ops alias + tip CN uses `tenant_id`) |
| **36 model/ECM** | **FAIL/BLOCKED** | Gate looked for `OPENFDD_OPS_A/B_PASSWORD`; Railway vars are `OPENFDD_USER_*_OPS_PASSWORD` — alias missing |

**Follow-up tip `3.5.35`:** rcx presets building ACL · gate26 structured verdict · OPS password aliases · live ACL patch for `central:bldg2` (+ HUP). Then backup+re-pin + **full** re-stress.



**Artifacts:** `reports/wave_u_enhanced_stress_20260920T152613Z/` · oracle twin `reports/wave_u_enhanced_stress_oracle_20260920T153722Z/` · ZAP AF disposable `reports/security/zap_af_disposable_20260920T150920Z/` · HTTPS peer `reports/security/standalone_https_probe.json`

| # | Check | Result |
|---|--------|--------|
| 1 | `tests/security` (55) | **PASS** |
| 2 | `tests/qualification` (ZAP AF hygiene) | **PASS** (selftest BLOCKED honesty) |
| 3 | HTTPS peer `--selftest` | **PASS** |
| 4 | Gate 26 MQTT ACL `EXECUTE=1` (live mosquitto observer) | **PASS** (own OK / foreign deny) |
| 5 | Gate 36 model/ECM | **BLOCKED** (no `OPENFDD_OPS_A/B_PASSWORD` — honesty) |
| 6 | Gate 36 MV twin vs live Railway hub (`EXECUTE=1` + `OPENFDD_API_BASE`) | **FAIL** — see BUG `wu-mv-404-pre-pin` |
| 7 | Gate 36 MV twin oracle-only (`EXECUTE=1`, no API base) | **PASS** (intercept=500 slope=2 savings=300) |
| 8 | Nessus importer `--selftest` | **PASS** |
| 9 | ECM pytest G14/changepoint/mv | **13 PASS** |
| 10 | Fieldbus fail-closed unit tests | **4 PASS** |
| 11 | Disposable ZAP AF (`sha-4d3a6b0`) | **PASS** High=0 Medium=0 |
| CI | #959 Rust fmt/clippy/tests + fdd-engine | **PASS** on `1ba4f7b6` |

### BUGS found this go-around (log before / with tip)

| ID | Severity | Status | Notes |
|----|----------|--------|-------|
| **ci-959-rustfmt** | CI | **FIXED** | `matches!` / package stamp helpers needed `cargo fmt` (`61814cb`, `9a49f4fa`) |
| **ci-959-react-alert** | CI | **FIXED** | `MvChangePointPanel` used `variant="error"`; AlertVariant is `danger` (`1ba4f7b6`) |
| **ci-959-pyyaml-qual** | CI | **FIXED** | AppSec qualification imported ZAP runner without PyYAML — install step added |
| **ci-959-docs-guard** | CI | **FIXED** | Cookbook link edits blocked; reverted — IPMVP lives under `docs/ecm/` |
| **wu-mv-404-pre-pin** | Soft-OPEN / FQ gate | **FIXED** | Hub re-pin `sha-f44b45f` · `POST /api/analytics/mv` → **HTTP 200** `ok:true` (smoke 2026-09-20T19:45Z). Gate 36 twin still must PASS under MEGA. |
| **wu-model-ecm-creds** | Soft-OPEN | **CLEARED for MEGA** | Railway has `OPENFDD_USER_ACME_OPS_PASSWORD` / `OPENFDD_USER_B100_OPS_PASSWORD` (stress fetches ops_a/ops_b len=32). Prior BLOCKED was missing fetch names. |
| **wu-w7-mega-20260922T213831Z** | Soft-OPEN / tip | **FAIL (not FQ)** | Hub `sha-9da9902` / 3.5.45. MEGA `reports/nightly-ot-bench_20260922T213831Z/` `fully_qualified=false`. FAILs: (1) gate35 pause published to `buildings/lab/` — edges lacked `site_id` when `has_telemetry=false` → harness defaulted `OPENFDD_SITE_ID=lab`; (2) gate25 foreign analytics TimeoutError under load (idle 403 ~300ms); (3) gate37 `/api/analytics/runtime` HTTP 502 under load (idle 200). 25b/26 BLOCKED. Patch tip in flight. |
| **wu-vim1-oa-t-kit** | Ops | **CLOSED (W6)** | Kit restored `deploy/mqtt/kits/ACME__vim-1/` + fieldbus `OPENFDD_RAILWAY_EDGE_ID=vim-1`. Hub health `ingest_reject=0` under steady poll (edges=1, last_ingest fresh) — Soft-OPEN closed. |
| **wu-acme-fdd-slow** | Perf (not hang) | Soft note | Hang Soft-OPEN **CLOSED** (20m reclaim + 900s timeout). ACME may still be slow/timeout under load — not indefinite `running` |
| **wu-s4-fq-mega** | Soft-OPEN | **CLOSED** | MEGA `20260921T021332Z` `fully_qualified=true` · OPS PINNED `sha-1677c33` / 3.5.37 |
| **wu-trivy-tip-digest** | Soft-OPEN | **W1 RESCANED** | `reports/trivy-wave-u/sha-7ad6479/SUMMARY.md` — web nginx H/C 0/0 (`1.28.3-r7`); Debian/caddy TRACKED; prior `sha-af4086f` historical |
| **wu-bacnet-ci-api-key** | CI | **FIXED #960** | Optional BACnet smoke supplies `OPENFDD_FIELDBUS_API_KEY` after fail-closed |
| **wu-bacnet-ci-ro-key-mode** | CI | **FIXED (#966)** | Keys 640 + writable broker mount; e2e PASS on tip `sha-af4086f` / 3.5.38 |
| **wu-pypi-publish-4.4.3** | Residual | **CLOSED** | PyPI `open-fdd==4.4.3` live; **4.4.4** published (retag after #983) |
| **wu-pypi-publish-4.4.4** | Residual | **CLOSED** | `open-fdd==4.4.4` on PyPI (`ecm_context_v1`) |
| **agent-report-chart-parity** | Soft-OPEN | **OPEN / W-CHART** | Agent Typst/PDF charts vs React Plotly parity — [agent_report_chart_parity.plan.md](../../.cursor/plans/agent_report_chart_parity.plan.md) |
| **wu-dm-07-10** | Soft-OPEN | **PARTIAL (W4 tip)** | DM-07/08 CLOSED (V5). **CLOSED on W4:** EQ-VOCAB · ECM-ADAPT · DM-10 narrow (`ofdd_haystack_projection_v1`, no false `hs:sensor`) · Pages. **PARTIAL:** DM-09 SELECT cap + baseline doc. **Soft-OPEN residual:** PERF-1 scale RSS · EQ-PERSIST · ECM REST/MCP |
| **wu-mt-breadth** | Soft-OPEN | Soft-OPEN honesty | Continue IMPLEMENTED matrix later; inventory cited on tip |
| **wu-v6-mega-20260921T204702Z** | Soft-OPEN / tip | **CLOSED FQ** | Tip **3.5.43** / `sha-7ad6479` (#978). MEGA `20260921T234148Z` `fully_qualified=true` (gate 00 retest after login throttle; all 25/25b/26/17/36/37 PASS). |
| **w7-mega-20260922T213831Z** | Soft-OPEN / tip | **OPEN (FAIL logged)** | Tip **3.5.45** / `sha-9da9902`. MEGA `20260922T213831Z` `fully_qualified=false` (35 lab site / 25 timeout / 37 502 / 26 ACL unset). Tip **3.5.46** closed 35/37/26 on re-MEGA; residual sensor-health → **3.5.47**. |
| **w7-mega-20260923T004400Z** | Soft-OPEN / tip | **OPEN (almost FQ)** | Tip **3.5.46** / `sha-5660837`. Gates 35/37/26 PASS; gate 25 own sensor-health **502** (unbounded UNION ALL on ~54k ACME parts). Patch tip **3.5.47**. |
| **w7-acme-tenant-history-fanout** | Soft-OPEN / ops | **OPEN (tip scans)** | Compactor/stats see `tenants/*/history` on **3.5.47**; live compact Soft-OPEN until hub V8 run reduces ~54k parts. |

**Do not claim:** Nessus assessment PASS · readiness VERIFIED while Critical/High unresolved · Soft-OPEN CLOSED without measured evidence. |
