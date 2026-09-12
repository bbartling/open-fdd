# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-09-12 (Wave M **ACTIVE** · Wave L **3.5.6 PINNED** held · mode OFF)  
**Platform:** Railway hub + bensbench **x86 fieldbus only** (no Raspberry Pi in Open-FDD stress)  
**Tip / pin (ops):** `e80237c0` · VERSION **3.5.6** · health **`3.5.6+e80237c0e758`** · GHCR **central/web/mqtt/fieldbus `sha-e80237c`** · `multi_tenant=false` · `historian_prefix=""` · `active_tenant_id=legacy` · `tenant_budgets=false`  
**Docs tip (post-pin; ops held):** `3cc96ddf` · **`sha-3cc96dd`** · Wave M M0 **#917** · product tip advances with **3.5.7** Wave M durable PR (ops held until re-pin) · prior `#916`/`sha-6987ef9` — **do not re-pin Railway** for docs-only tips  
**Rollback pin (Wave K):** `9c3e8b1c` · **`sha-9c3e8b1`** · **`3.4.0+9c3e8b1c30c1`** · MEGAs stress `20260910T021557Z` · docs **#890**  
**Prior Wave L tip (L5 ops):** `c5b3ccc9` · **`sha-c5b3ccc`** · **`3.5.5+c5b3ccc947c8`** · docs **#906**  
**Prior Wave L tip (L5 product):** `ecd97a47` · **`sha-ecd97a4`** · **`3.5.5+ecd97a473405`** · product **#904** · docs **#905**  
**Prior Wave L tip (L4):** `d67d27b9` · **`sha-d67d27b`** · **`3.5.3+d67d27b9e791`** · product **#901** · docs **#902**  
**Prior Wave L tip (L3):** `be653663` · **`sha-be65366`** · **`3.5.2+be65366316bb`** · product **#899** · docs **#900**  
**Prior Wave L tip (L2 ops):** `af08ac7b` · **`sha-af08ac7`** · **`3.5.1+af08ac7b9889`** · product **#894** · flake-fix **#897**  
**Prior Wave L tip (L1):** `a11b6cb1` · **`sha-a11b6cb`** · **`3.5.0+a11b6cb181fc`** · product **#891**  
**Last CLOSED tip (Wave J):** `c1b1aa52` · **`sha-c1b1aa5`** · **`3.3.41+c1b1aa52806b`** · product **#877** · CI/gates **#878** · docs Stage A **#876**  
**Field:** bensbench x86 `openfdd-fieldbus` → Railway MQTTS (`bldg2` / client `pi-1` kit). Dual-publish AV `9101`: `bldg2-zone-loopback` **`zone_t`+`oa_t`**, `hosted-weather` **`web_oa_t`**.  
**Backup:** `~/openfdd-backups/railway/20260912T031216Z/` (pre–`sha-e80237c` L8 re-pin; L5c `20260911T185021Z/`; product L5 `20260911T172130Z/`; L4 `20260911T123823Z/`; L3 `20260911T030541Z/`; L2b `20260911T004519Z/`; L2 product `20260910T230450Z/`; L1 `20260910T161828Z/`)  
**Program (CLOSED / PINNED):** Wave L — **multi-client shared hosting 3.5.6** (tenant-partitioned Parquet + control plane; **not** Postgres time-series) · tip `sha-e80237c` · stress `reports/nightly-ot-bench_20260912T033836Z/` **`fully_qualified=true`** (gates 00–17) · Cursor [`wave_l_shared_db_mega_master`](../../../.cursor/plans/wave_l_shared_db_mega_master.plan.md) · repo [`openfdd_wave_l_shared_db_mega_program.plan.md`](patch_trains/openfdd_wave_l_shared_db_mega_program.plan.md)  
**Program (CLOSED):** Wave K — **3.4.0 filesystem-historian pin** · tip `sha-9c3e8b1` · stress `reports/nightly-ot-bench_20260910T021557Z/` **`fully_qualified=true`** (gates 00–10) · harness fix **#889** · Cursor [`wave_k_340_filesystem_pin_master`](../../../.cursor/plans/wave_k_340_filesystem_pin_master.plan.md)  
**Program (prior CLOSED):** Wave J — Cursor [`wave_j_df_boundary_master`](../../../.cursor/plans/wave_j_df_boundary_master.plan.md) · tip `sha-c1b1aa5` / 3.3.41  
**Program (prior CLOSED):** Wave I — Cursor [`wave_i_app_test_mega_master`](../../../.cursor/plans/wave_i_app_test_mega_master.plan.md) · tip `sha-d1312b0` / 3.3.40  
**Stress (Wave K closeout):** `reports/nightly-ot-bench_20260910T021557Z/` · **`fully_qualified=true`** (gates 00–10 incl. ZAP + MCP + Wave I + Wave K MEGAs)  
**Stress (Wave L L8 closeout):** `reports/nightly-ot-bench_20260912T033836Z/` · **`fully_qualified=true`** (gates **00–17** incl. ZAP + MCP + Wave I/K + Wave L 11–17; **no `SKIP_ZAP`**) · candidate health `3.5.6+e80237c0e758` · mode OFF  
**L8 smoke (pre-stress):** gates **11–17 PASS** · `/tmp/wave_l_l8_smoke_20260912T033741Z/` · health `3.5.6+e80237c0e758` · fieldbus `sha-e80237c`  
**L5 smoke:** gates **11+12+13+14+15 PASS** · `/tmp/wave_l_l5c_smoke_20260911T185328Z/` (ops `sha-c5b3ccc`) · prior product smoke `/tmp/wave_l_l5_smoke_20260911T172505Z/` (`sha-ecd97a4`) · health `3.5.5+c5b3ccc947c8` · `multi_tenant=false` · `active_tenant_id=legacy` · `tenant_budgets=false` · fieldbus `sha-c5b3ccc`  
**L4 smoke:** gates **11+12+13+14 PASS** · `/tmp/wave_l_l4_smoke_20260911T124238Z/` · health `3.5.3+d67d27b9e791` · `multi_tenant=false` · `active_tenant_id=legacy` · `tenant_session=true` · fieldbus `sha-d67d27b`  
**L3 smoke:** gates **11+12+13 PASS** · `/tmp/wave_l_l3_smoke_20260911T032648Z/` · health `3.5.2+be65366316bb` · `multi_tenant=false` · ingest_ok soak · fieldbus `sha-be65366`  
**L2 smoke:** gates **11+12 PASS** · `/tmp/wave_l_l2_smoke_20260910T230823Z/` (product `sha-2dea571`) · re-pin smoke `/tmp/wave_l_l2b_smoke_20260911T005453Z/` · health `3.5.1+af08ac7b9889` · `multi_tenant=false` · empty `historian_prefix` · ingest_ok soak  
**L1 smoke:** gate 11 PASS · `/tmp/wave_l_l1_smoke_20260910T165010Z/` · health `3.5.0+a11b6cb181fc`  
**Deferred (Wave L carry → Wave M):** Stage C IdP/MFA (M4 late) · [#782](https://github.com/bbartling/open-fdd/issues/782) → **M1** · sql-anomaly → **M2** · AFDD flood → **M5 gate 12**  
**Plan TODOs:** Wave L CLOSED; Wave M **ACTIVE** — Track D durable results + residuals M1–M4 + enhanced M5  
**K1:** MEGAs **#884 MERGED** (`5aed663c`). Docs K2/K3 → **#885**.  
**K1b:** Plot-span **#886 MERGED** (`cee2f4ec`) — smoke on `sha-cee2f4e`.  
**L1:** TenantContext **#891 MERGED** (`a11b6cb1`) — VERSION **3.5.0** · mode OFF  
**L2:** Tenant Parquet roots **#894 MERGED** (`2dea571c`) — VERSION **3.5.1** · mode OFF · gate 12  
**L3:** MQTTS namespace + ACL + identity **#899 MERGED** (`be653663`) — VERSION **3.5.2** · mode OFF · gate 13  
**L4:** Tenant UI/session **#901 MERGED** (`d67d27b9`) — VERSION **3.5.3** · mode OFF · gate 14  
**L5:** Per-tenant budgets **#903 MERGED** (`581edf3e` / 3.5.4) + product UX **#904 MERGED** (`ecd97a47` / 3.5.5) + docs/harness **#905 MERGED** (`c5b3ccc9`) · mode OFF · gate 15  
**L6+L7:** A/B isolation + tip digest + legacy migrate dry-run **#908 MERGED** (`1d15d423` / 3.5.6) + fieldbus env-lock flake **#909 MERGED** (`e80237c0` / **3.5.6 PINNED**) · gates 16–17  
**L8 docs:** BUG_REPORT PINNED **#910** · plan-mirror **#911+#912** · docs tip **#913+#914** · tenant ENV_LOCK flake fix **#915** — ops tip remains **`sha-e80237c`**  
**Wait filler:** Vibe13 Part B (separate repo) during Open-FDD CI/Publish  
**Pis freed (not in Open-FDD stress):** bosspi · BensFakeAhu · Zone1VAV.

## OPEN / tracked bugs (post-3.3.33)

| ID | Status | Symptom | Evidence | Next |
|----|--------|---------|----------|------|
| **sensor-faults-matrix** | **CLOSED** (Wave K / 3.4.0 / gate 10) | Was: Lakeside Sensor faults empty | Stress `20260910T021557Z`: matched=71 rows=71 | — |
| **mqtt-bacnet-quad-points** | **CLOSED** (Wave K / 3.4.0 / gate 10) | Was: dual-publish collapsed; RH missing | Gate 10: zone_t=135 oa_t=65 zone_rh=19 web_oa_t=34 | — |
| **data-model-all-sites** | **CLOSED** (Wave K / 3.4.0 / gate 10) | Was: empty MQTT roles; weak cross-site | Gate 10: mapping roles>0; cross-site fail_closed | — |
| **fdd-series-recent-only** | **CLOSED** (K1b / #886 / `sha-cee2f4e`) | Was: `GET /api/fdd/series` recent-only DESC LIMIT | Smoke 2026-09-09: AHU_1 FC1 series n=7109 span `2026-03-16→07-17` matches Inspect | — |
| **econ-points-prefix-limit** | **CLOSED** (K1b / #886 / `sha-cee2f4e`) | Was: economizer points prefix LIMIT truncated early window | Smoke: `POST /api/analytics/economizer` n=8000 span `2026-03-16→07-17` | — |
| **rcx-oat-scatter-cap** | **CLOSED** (K1b / #886 / `sha-cee2f4e`) | Was: OAT scatter clamp 12k ended ~Apr | Smoke: `hw_reset_scatter` max_points=20000 → n=20000 (was 12k) | — |
| **lakeside-read-csv-missing** | **CLOSED** (3.3.40 / Wave I) | Was: LAKESIDE_ES FDD `read_csv not found` | #872 `register_csv`; stress gate09 no `read_csv` | — |
| **overview-tables-unfiltered** | **CLOSED** (3.3.40 / Wave I) | Was: MQTT Overview looked table-filtered vs CSV | #872 Overview chrome pad + Weather section always render | — |
| **data-model-json-export** | **CLOSED** (3.3.40 / Wave I) | Was: Export JSON dead for MQTT | #872 historian mapping + Export; mapping `bldg2` equipment=2 | — |
| **plot-default-full-span-b100** | **CLOSED** (3.3.40 / Wave I) | Was: B100 plots July-only | #872 span-preserving Inspect; gate09 AHU_1 `plot_days=123.4` (#873) | — |
| **weather-local-vs-web-bldg2** | **CLOSED** (3.3.40 / Wave I) | Was: bldg2 bas-vs-web empty | #872 dual OAT catalog; gate09 `bas_vs_web` points>0 | — |
| **mqtt-bldg2-plot-surface** | **CLOSED** (3.3.40 / Wave I) | Was: MQTT plots empty/wrong roles | Inspect `zone_t` non_null=696; dual OAT live | — |
| **wave-i-stress-gates** | **CLOSED** (3.3.40 / Wave I) | Was: stress green while basics broken | Gate `09_wave_i_app_test_megas` required; #873 AHU_1 fix | — |
| **mqtt-monitor-sse-782** | **CLOSED** (Wave M M1 / 3.5.7) | JWT `GET /api/mqtt/monitor/stream` SSE + Ops EventSource with 1s poll fallback; no browser→Mosquitto WS | [#782](https://github.com/bbartling/open-fdd/issues/782) | — |
| **df-boundary-repair** | **CLOSED** (Wave J / 3.3.41) | Was: stale pandas/UI docs + incomplete Python-absence / DF provenance | #876 Stage A · #878 policy+image+soak · tip Python-absence PASS | — |
| **cookbook-parity-875** | **CLOSED** (3.3.41 / #877) | Was: FC3 tol/fan priority; VAV-2 fractional occupancy | #877 · #875 closed · oracle_parity FC3/VAV-2 | — |
| **mqtt-ingest-stall** | **CLOSED** (3.3.34) | Was: flat `ingest_ok` after mqtt bounce until central redeploy | #860 · tip `sha-9aebf42` · smoke `reports/waveD_railway_smoke_20260906T173032Z/` | — |
| **railway-ui-fdd-stale** | **CLOSED** (Wave E) | Was: building filter / scoped FDD UX across sites | Tip `sha-9aebf42`: Overview clears on site change; PlantHealthSections empty shells; equipment=8 / zone-other rows=7 | No VERSION — UX already on tip |
| **bldg2-overview-signoff** | **CLOSED** (Wave H) | Was: SPA charts weak; buyer mash Run/Update | #868/#869 · Inspect/RCx points>0; Overview auto-load | — |
| **bldg2-site-hygiene** | **CLOSED** (Wave H ops) | Was: ghost equip under bldg2 | Hist purge → equip=`bldg2-zone-loopback`+`hosted-weather` only | — |
| **mqtt-inspect-plot-parity** | **CLOSED** (3.3.38/39) | Was: Inspect/FDD/RCx empty on MQTT | Inspect loopback points>3000; RCx zone_comfort_rank includes loopback | — |
| **mqtt-zone-t-rcx** | **CLOSED** (3.3.38) | Was: VAV filter skipped `bldg2-zone-loopback` | #868 `rcx_eq_filter` ZONE/LOOPBACK | — |
| **ui-demo-freshness** | **CLOSED** (3.3.39) | Was: mash Update analytics every visit | #869 Overview auto-load + focus soft-refresh | — |
| **demo-sites-health** | **CLOSED** (Wave H) | Lakeside / B100 / B50 charts+data | Inspect pts: Lakeside HP 8000 / B100 8000 / B50 136; stress Creekside+B100 PASS | Superseded residual → Wave I Lakeside `read_csv` MEGA |
| **vibe19-operational-gate-lab** | **CLOSED** (3.3.37 / Wave G) | Operational-gate trio SQL-bound | #864 · tip `sha-a40787b` | — |
| **hybrid-ml-physics-ahu-vav** | **ABANDONED** | Was: physics/RCA / ML / E+ hybrid Wave G | Felt bogus 2026-09-07 | Do not implement |
| **sql-anomaly-screening** | **LIVE-lab** (Wave M M2 / 3.5.7) | Lab-safe `OPENFDD_SQL_ANOMALY_SCREENING=1` + `/api/analytics/sql-anomaly/status`; default OFF | flag gated | expand self/peer rules later |
| **wave-l-l1-tenant-context** | **CLOSED** (Wave L L1 / 3.5.0 / `sha-a11b6cb`) | Control plane + `TenantContext` + mode OFF; health/tenants; gate 11 | #891 · tip smoke `/tmp/wave_l_l1_smoke_20260910T165010Z/` · `multi_tenant=false` | L2 Parquet isolation |
| **wave-l-l2-parquet-roots** | **CLOSED** (Wave L L2 / 3.5.1 / `sha-2dea571` product · ops tip `sha-af08ac7`) | Tenant-partitioned Parquet roots + DF path scoping; gate 12; mode OFF = hub root | #894 · smoke `/tmp/wave_l_l2_smoke_20260910T230823Z/` + `/tmp/wave_l_l2b_smoke_20260911T005453Z/` · gates 11+12 PASS · flake-fix #897 | L3 MQTTS isolation |
| **wave-l-l3-mqtts-namespace** | **CLOSED** (Wave L L3 / 3.5.2 / `sha-be65366`) | MQTTS `TopicBuilder` / `parse_topic` + ingest identity provenance; gate 13; mode OFF = legacy `sites/…` | #899 · smoke `/tmp/wave_l_l3_smoke_20260911T032648Z/` · gates 11+12+13 PASS · backup `20260911T030541Z` | L4 Tenant UI/session |
| **wave-l-l4-tenant-ui-session** | **CLOSED** (Wave L L4 / 3.5.3 / `sha-d67d27b`) | Single-domain tenant session: auth/me + select + SPA chrome; gate 14; mode OFF = legacy no-op | #901 · smoke `/tmp/wave_l_l4_smoke_20260911T124238Z/` · gates 11–14 PASS · backup `20260911T123823Z` | L5 budgets + UX |
| **wave-l-l5-tenant-budgets** | **CLOSED** (Wave L L5 / 3.5.5 / `sha-c5b3ccc`) | Per-tenant budgets OFF-safe (#903) + product UX Dump/Twin/OAT/zone comfort (#904) + docs/harness (#905); gate 15 | #903 · #904 · #905 · smoke `/tmp/wave_l_l5c_smoke_20260911T185328Z/` · gates 11–15 PASS · backup `20260911T185021Z` · gate15 jq `false//` harness fix | L6 qual hardening |
| **wave-l-l6-ab-isolation** | **CLOSED** (Wave L L6 / 3.5.6 / `sha-e80237c`) | Tier-2 A/B path+MQTT harness + tip digest scan + ZAP AF mode-OFF; gate 16 | #908 · #909 · smoke `/tmp/wave_l_l8_smoke_20260912T033741Z/` · stress gate 16 PASS | L7 migrate |
| **wave-l-l7-legacy-migrate** | **CLOSED** (Wave L L7 / 3.5.6 / `sha-e80237c`) | Legacy-tenant migrate dry-run + operator checklist; APPLY refused on HTTPS; gate 17 | #908 · checklist `WAVE_L_LEGACY_MIGRATE_CHECKLIST.md` · stress gate 17 PASS | L8 pin |
| **wave-l-l8-pin** | **CLOSED** (Wave L L8 / **3.5.6 PINNED** / `sha-e80237c`) | Enhanced full stress gates 00–17; `fully_qualified=true`; mode OFF; plan TODOs closed except SQL PARKED | stress `reports/nightly-ot-bench_20260912T033836Z/` · backup `20260912T031216Z` · no `SKIP_ZAP` · docs #910+#911 | — (outside Wave L) |
| **lab-tuner-vibe19-parity** | **CLOSED** (3.3.37) | Vibe19 Lab tuners → production (~217→~444) | #864 · stress `reports/nightly-ot-bench_20260907T183808Z/` · `fully_qualified=true` | — |
| **ghcr-publish-hub-blocked-by-fieldbus** | **CLOSED** (#865) | Serial Publish put mqtt after multi-arch fieldbus | Merged 2026-09-07; tip-completeness workflow live | — |
| **mqtt-overview-spa-parity** | **CLOSED** (3.3.33) | Was: equipment=0 for MQTT `bldg2` → empty Overview | #856 · probe + stress | — |
| **mqtt-fieldbus-tip-pin-sync** | **CLOSED** (3.3.34) | Tip pin same-sha after Wave D | All services `sha-9aebf42` | — |
| **qualification-viewer-login** | **CLOSED** (3.3.28) | `OPENFDD_VIEWER_PASSWORD` → `username=viewer` JWT | Railway var set | Optional auth_matrix path → Wave F soft |
| **wave-c-railway-smoke** | **CLOSED** | Wave C smoke | `reports/waveC_railway_smoke_final/` · #854 | — |

### Wave H closeout (2026-09-08T02:13Z)

| Check | Result |
|-------|--------|
| Hub | `3.3.39+2e136b482786` · central/mqtt/web **Online** · `sha-2e136b4` |
| Tip gate | `./scripts/check_ghcr_tip_stack.sh sha-2e136b4` **PASS** |
| Ingest | `edges:1` · `ingest_ok` climbing · fieldbus `sha-2e136b4` |
| bldg2 equip | **2** — `bldg2-zone-loopback`, `hosted-weather` |
| Inspect / RCx | loopback Inspect points>0 · `zone_comfort_rank` includes loopback |
| Demo sites | Lakeside / B100 / B50 Inspect data visible |
| Stress | `reports/nightly-ot-bench_20260908T021007Z/` **`fully_qualified=true`** |
| H5 bldg2 OAT overlay | **CLOSED** Wave I — `weather-local-vs-web-bldg2` |

### Wave I closeout (2026-09-08T18:25Z)

| Check | Result |
|-------|--------|
| Hub | `3.3.40+d1312b0ccb07` · central/mqtt/web **Online** · `sha-d1312b0` |
| Tip gate | GHCR tip completeness **PASS** on `d1312b0c` |
| Backup / pin | `~/openfdd-backups/railway/20260908T171523Z/` · full-stack + fieldbus `sha-d1312b0` |
| Ingest | `edges:1` · `ingest_ok` climbing · dual OAT publishing |
| Gate 09 | Lakeside FC1 / mapping bldg2 / Inspect `zone_t` / bas-vs-web / B100 span **PASS** |
| Stress | `reports/nightly-ot-bench_20260908T182149Z/` **`fully_qualified=true`** (00–09) |
| Deferred | #782 MQTT monitor SSE — **do not** combine with DF-boundary mega |

### Wave J closeout (2026-09-09T01:10Z)

| Check | Result |
|-------|--------|
| Hub | `3.3.41+c1b1aa52806b` · central/mqtt/web **Online** · `sha-c1b1aa5` |
| Tip gate | `./scripts/check_ghcr_tip_stack.sh sha-c1b1aa5` **PASS** · GHCR tip completeness Actions **PASS** |
| Python-absence | `./scripts/check_ghcr_tip_python_absence.sh sha-c1b1aa5` **PASS** (central/web/mqtt/fieldbus) |
| Backup / pin | `~/openfdd-backups/railway/20260909T002816Z/` · hub + fieldbus `sha-c1b1aa5` |
| Landed | #876 Stage A docs · #877 FC3/VAV-2 (3.3.41) · #878 policy+image+soak · J4 waive · #782 deferred |
| Stress | `reports/nightly-ot-bench_20260909T010712Z/` **`fully_qualified=true`** (00–09) |
| Note | First stress attempt failed gate 08 when sticky `.env` `OPENFDD_IMAGE_TAG` clobbered MCP pin — fixed in `load_bench_env` |

### Wave H kickoff probe (2026-09-07T20:35Z)

| Check | Result |
|-------|--------|
| Hub | `3.3.37+a40787b4e033` · central/mqtt/web **Online** · `sha-a40787b` |
| Tip gate | `./scripts/check_ghcr_tip_stack.sh sha-a40787b` **PASS** |
| Ingest | `edges:1` · `ingest_ok` **119+** climbing |
| Package buildings | `BUILDING_100`, `BUILDING_50`, `LAKESIDE_ES`, `OPENFDD_SYNTHETIC_59_RULE_WEEK_V1`, `bldg2` (5) |
| bldg2 equip | 8 ids incl. ghosts + `bldg2-zone-loopback` |
| FDD series loopback | **PASS** — `zone_t` non-null **2934** rows |
| RCx `zone_comfort_rank` | **FAIL** — 0 points (VAV id-name filter) |

### MQTTS pipeline health check (2026-09-06T17:39Z) — Wave D

| Check | Result |
|-------|--------|
| Hub | `3.3.34+9aebf42bf767` · `edges:1` |
| Fieldbus | `openfdd-fieldbus:sha-9aebf42` healthy |
| Edge | `pi-1` / `bldg2` `has_telemetry:true` |
| Ingest | **PASS** — `ingest_ok` **2→5** over ~3 min; after **mqtt redeploy** (no central redeploy) **6→10** then smoke at **11** |
| Smoke | Wave C smoke **PASS** — `reports/waveD_railway_smoke_20260906T173032Z/` |
| Residual | Overview SPA chrome → Wave E |

## Next patch cycle (copy into `.cursor/plans/patch_cycle_3.3.N_<slug>.plan.md`)

Template + commands: [`PATCH_CYCLE.md`](PATCH_CYCLE.md). Check boxes as you go. Do **not** bump VERSION for a pure evidence/docs PR.

### Upcoming trains (Cursor plans — optimized waves 2026-09-06)

**Source of truth:** [`patch_trains/`](patch_trains/) · [`BENCH_RECOVERY.md`](BENCH_RECOVERY.md) · [`recovery/AI_CONTEXT_HANDOFF.md`](recovery/AI_CONTEXT_HANDOFF.md).  
**Active:** Wave M — durable results + residuals ([`wave_m_residual_mega_0c09093d`](../../../.cursor/plans/wave_m_residual_mega_0c09093d.plan.md) · repo [`openfdd_wave_m_residual_mega_program.plan.md`](patch_trains/openfdd_wave_m_residual_mega_program.plan.md)). Prod `multi_tenant=false` until Stage C checklist.  
**Last closed:** Wave L [`wave_l_shared_db_mega_master`](../../../.cursor/plans/wave_l_shared_db_mega_master.plan.md) · ops tip `sha-e80237c` / **3.5.6** · stress `20260912T033836Z` **`fully_qualified=true`**. Prior Wave K tip `sha-9c3e8b1` / **3.4.0**.

**This round stress rule:** Mid-wave = smoke. **ONE** enhanced full stress at Wave M M5 (Wave L 00–17 + durable gates 1–12 incl. AFDD flood). Cite Wave L `20260912T033836Z` only for 3.5.6 PINNED claims until M5 lands.

| Rev / wave | In-repo / Cursor plan | Concern | Status |
|------------|----------------------|---------|--------|
| **Wave M master** | [`openfdd_wave_m_residual_mega_program.plan.md`](patch_trains/openfdd_wave_m_residual_mega_program.plan.md) | Durable results + release + residuals + enhanced stress | **ACTIVE** |
| **Wave L master** | [`openfdd_wave_l_shared_db_mega_program.plan.md`](patch_trains/openfdd_wave_l_shared_db_mega_program.plan.md) | **3.5.x multi-client shared hosting** (tenant Parquet + control plane) | **CLOSED / PINNED** (`sha-e80237c` / 3.5.6; stress `20260912T033836Z`) |
| **Wave K master** | [`openfdd_wave_k_340_filesystem_pin_program.plan.md`](patch_trains/openfdd_wave_k_340_filesystem_pin_program.plan.md) | **3.4.0 pin** + MEGAs + historian freeze + Phase-0 ADR | **CLOSED / PINNED** |
| **Wave J master** | [`wave_j_df_boundary_master`](../../../.cursor/plans/wave_j_df_boundary_master.plan.md) | DF-boundary + #875 | **RETIRED / CLOSED** |
| **Wave I master** | [`wave_i_app_test_mega_master`](../../../.cursor/plans/wave_i_app_test_mega_master.plan.md) | App-test MEGAs | **RETIRED / CLOSED** |
| **Wave H** | Cursor post_waveg residual H | Demo charts / UI freshness | **CLOSED** |
| **Wave G / 3.3.37–3.3.40** | [`openfdd_lab_tuner_parity_program.plan.md`](patch_trains/openfdd_lab_tuner_parity_program.plan.md) | Lab tuner Vibe19 parity | **CLOSED** — #864 · tip `sha-a40787b` |
| **#782 SSE** | [`mqtt_monitor_sse_782`](../../../.cursor/plans/mqtt_monitor_sse_782.plan.md) | MQTT monitor SSE | **CLOSED** (3.5.7) |
| **sql-anomaly** | Wave M M2 | SQL self/peer anomaly | **LIVE-lab** (3.5.7 flag) |

**Tuner reference:** Vibe19 UI **~414** vs Lab tip **~444** after Wave G (was ~217) — [`lab_tuners_snapshot_post_wave_g.json`](recovery/lab_tuners_snapshot_post_wave_g.json). G0 matrix: [`recovery/lab_vibe19_tuner_gap_matrix_g0.json`](recovery/lab_vibe19_tuner_gap_matrix_g0.json). RCx: [`RCX_PLOTS_BY_HVAC.md`](../RCX_PLOTS_BY_HVAC.md).

## Verdict — Wave G Lab tuner parity 3.3.37 (CLOSED 2026-09-07)

| Check | Evidence |
|-------|----------|
| Product | VERSION **3.3.37** · PR **#864** merged `a40787b4` |
| Lab sum | **~444** · `recovery/lab_tuners_snapshot_post_wave_g.json` |
| GHCR tip | `sha-a40787b` central/web/mqtt/fieldbus (Publish completed after fieldbus delay) |
| Tip gate | `./scripts/check_ghcr_tip_stack.sh sha-a40787b` **PASS** |
| Backup | `~/openfdd-backups/railway/20260907T153333Z/` |
| Railway pin | health **`3.3.37+a40787b4e033`** · edges:1 · fieldbus `sha-a40787b` |
| Closeout stress | **PASS** · `fully_qualified=true` · `reports/nightly-ot-bench_20260907T183808Z/` · gates 00–08 incl. ZAP |
| GHCR follow-up | **#865** — hub publish parallel to fieldbus + tip completeness workflow |

**Publish lesson:** mqtt was sequenced after multi-arch fieldbus in one job — tip looked broken for hours. Fix in #865.

| TODO | 3.3.24 | 3.3.25 | 3.3.26 Wave A | 3.3.28 Wave B |
|------|--------|--------|---------------|---------------|
| Hygiene START | [x] | [x] | [x] | [x] |
| VERSION bump | [x] #842 | [x] #844 | [x] #847 → `3.3.26` | [x] #852 → `3.3.28` |
| One-concern fix | [x] GL36 | [x] SV-RANGE + ECON-4 | [x] qual harness | [x] #851 scope + Lab + viewer |
| PR squash-merge | [x] | [x] | [x] #847 · README #848 · docs #849/#850 | [x] #852 |
| GHCR full stack tip | [~] hybrid | [~] hybrid | [x] all `sha-c354ea9` | [x] all `sha-10d1ec5` |
| Railway backup + re-pin | [x] | [x] | [x] backup `171439Z` | [x] backup `195204Z` |
| Stress CSV + ZAP + Overview | [x] | [x] | [x] matrix PASS; Overview #851 OPEN | [x] `fully_qualified=true`; Overview #851 CLOSED |
| Verdict | [x] | [x] | [x] | [x] CLOSED |

Do **not** reopen #763 / #805 for depth. Do **not** put Pis back on the closeout path.

Private OT LAN addresses, vendor lake credentials, and tunnel endpoints live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — 3.3.34 MQTT ingest reconnect (2026-09-06) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #860 → `9aebf42b`; VERSION **3.3.34** |
| Fix | `openfdd_mqtt` tears down event stream on poll Err → central re-subscribe |
| Health | **`3.3.34+9aebf42bf767`** |
| GHCR | central/web/mqtt/fieldbus **`sha-9aebf42`** |
| Backup | `~/openfdd-backups/railway/20260906T164054Z/` |
| Field | `openfdd_fieldbus_railway_up.sh sha-9aebf42` |
| Ingest prove | `ingest_ok` **2→5**; mqtt redeploy **without** central redeploy → **6→10** |
| Smoke | Wave C smoke **PASS** — `reports/waveD_railway_smoke_20260906T173032Z/` |
| Soft-OPEN | Full matrix still at closeout; Wave E next |

## Verdict — Soft-OPEN closeout (2026-09-06) — D–F CLOSED

| Check | Evidence |
|-------|----------|
| Tip | `3.3.34+9aebf42bf767` · GHCR `sha-9aebf42` · fieldbus healthy |
| Full stress | **PASS** `overall.fully_qualified=true` — `reports/nightly-ot-bench_20260906T190722Z/` (gates 00–08) |
| Overview MQTT | equipment count=8; zone-other rows=7; AFDD run ok — `reports/softopen_closeout_overview_*` |
| Waves | D (#860) · E (docs/API) · F (DEFER operational-gate) |
| Wave G | **OPEN** — Lab tuner parity (`post_softopen_wave_g_sql_anomaly_master_f7a8b9c0`); anomaly PARKED; hybrid ABANDONED |

## Verdict — Wave E Overview UI scope (2026-09-06) — CLOSED (no VERSION)

| Check | Evidence |
|-------|----------|
| Tip | unchanged `sha-9aebf42` / `3.3.34+9aebf42bf767` |
| Overview API | equipment `bldg2` **count=8**; zone-other **rows=7** — `reports/waveE_overview_probe_20260906T175230Z/` |
| Chrome | Building change clears Overview; health matrices render empty shells for missing families |
| Browser sign-off | **DEFERRED** — operator to confirm SPA `?site=bldg2` visually |
| Soft-OPEN | No GHCR retarget |

## Verdict — Wave F Lab residual (2026-09-06) — CLOSED (DEFER operational-gate)

| Check | Evidence |
|-------|----------|
| vibe19 operational-gate trio | **DEFERRED** — no SQL/session binding; Path B refuse fake sliders |
| Viewer login | Already **CLOSED** 3.3.28 |
| VERSION / images | No bump |

## Verdict — 3.3.33 MQTT Overview = CSV (2026-09-06) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #856 → `25826cf6`; VERSION **3.3.33** |
| Shipped | FDD equipment walks `history/building_id=` + `building=`; run/series use `register_historian_building`; buildings list unions historian sites |
| Health | **`3.3.33+25826cf67999`** |
| GHCR | central/web/mqtt/fieldbus **`sha-25826cf`** |
| Backup | `~/openfdd-backups/railway/20260906T030735Z/` |
| Field | `openfdd_fieldbus_railway_up.sh sha-25826cf`; edge `pi-1`/`bldg2` `has_telemetry` |
| Overview SPA gate | **PASS** — `GET /api/fdd/equipment?building_id=bldg2` **count=8** incl. `bldg2-zone-loopback` (`reports/wave333_overview_probe_20260906T031659Z/`) |
| Buildings picker | **PASS** — `bldg2` listed with CSV packages |
| Zone Other tables | **PASS** — rows=7; loopback present (tables not hidden) |
| AFDD | **PASS** — `POST /api/fdd/run` `{building_id:bldg2, rule_ids:[VAV-1,SV-RANGE]}` ok; succeeded=2 |
| STRESS | **PASS** `fully_qualified=true` — `reports/nightly-ot-bench_20260906T031744Z/` (gates 00–08) |
| Soft-OPEN | `railway-ui-fdd-stale` + browser sign-off → Wave E; **mqtt-ingest-stall** opened post-closeout |


## Verdict — Wave C isolated harness (2026-09-05) — CLOSED

| Check | Evidence |
|-------|----------|
| Merge | #854 → `5e9c3c28`; VERSION unchanged **3.3.28** (harness/docs; no GHCR retarget / no tip re-pin) |
| 3.3.30 ZAP AF | **PASS** CI `isolated` + local — OpenAPI+passive; High=0; pinned `zaproxy@sha256:781a2bda…` |
| 3.3.31 MQTTS | **PASS** allow / cross-site deny / foreign CA / QoS1 / reconnect |
| 3.3.32 restore+perf | **PASS** backup→empty volume + bounded API budgets |
| Entry | `run_wave_c_isolated.sh` · `wave-c-isolated.yml` · `railway_smoke_wave_c.sh` |
| Railway smoke | **PASS** `reports/waveC_railway_smoke_final/` — `3.3.28+10d1ec569e83`; `pi-1`/`bldg2`; `bldg2-zone-loopback` + `zone-air-temp`; Zone Other rows=7 |
| Product tip | remains **`sha-10d1ec5`** (Wave B); no full matrix (images/topology unchanged) |
| Field public ZAP | unchanged — public baseline only on live hub |

## Verdict — Wave B / 3.3.28 (2026-09-05) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #852 → `10d1ec56`; VERSION **3.3.28** |
| Shipped | Canonical historian scope `history/building_id=*`; hosted AV9101→`zone_t` catalog; Lab VAV-5/ECON-3/5/7/CHW-NOLOAD; `OPENFDD_VIEWER_PASSWORD` |
| Health | **`3.3.28+10d1ec569e83`** |
| GHCR | central/web/mcp/mqtt/fieldbus **`sha-10d1ec5`** |
| Backup | `~/openfdd-backups/railway/20260905T195204Z/` |
| Field | `openfdd_fieldbus_railway_up.sh sha-10d1ec5`; edges `pi-1`/`bldg2`; live role=`zone_t` |
| STRESS | **PASS** `fully_qualified=true` — `reports/nightly-ot-bench_20260905T220906Z/` (gates 00–08) |
| Overview MQTT | **CLOSED** [#851](https://github.com/bbartling/open-fdd/issues/851) — `building_id=bldg2` sensor-stats has `zone-air-temp`; Zone Other includes `bldg2-zone-loopback` (`reports/waveB_overview_close_20260905T221400Z/`) |
| Viewer login | **PASS** — Railway `OPENFDD_VIEWER_PASSWORD` |
| Ops follow-up | `ensure_bench_field_devices` RAILWAY_ONLY uses `field_devices.railway.example.toml` (do not clobber hosted catalog with OT bench example) |

## Verdict — Wave A tip pin / 3.3.27 (2026-09-05) — CLOSED (Overview → Wave B)

| Check | Evidence |
|-------|----------|
| Tip | `c354ea91` · health **`3.3.26+c354ea915865`** |
| GHCR | central/web/mcp/**mqtt/fieldbus** all **`sha-c354ea9`** |
| Field | `openfdd_fieldbus_railway_up.sh sha-c354ea9`; edges `pi-1`/`bldg2` `has_telemetry:true` |
| STRESS | **PASS** `fully_qualified=true` — `reports/nightly-ot-bench_20260905T181633Z/` |
| Docs | #849/#850 merged |
| Overview MQTT `zone_t` | carried to Wave B → **CLOSED** under 3.3.28 |

## Verdict — 3.3.26 qualification harness (2026-09-05) — CLOSED (with OPEN follow-ups)

| Check | Evidence |
|-------|----------|
| Product merge | #847 → `13ef8549`; docs #848/#849 → tip `c354ea91`; VERSION **3.3.26** |
| Health | **`3.3.26+c354ea915865`** (central+web **`sha-c354ea9`**) |
| GHCR | tip pin completed under Wave A (all `sha-c354ea9`) |
| Backup | `~/openfdd-backups/railway/20260905T171439Z/` |
| Field | tip fieldbus; edges `pi-1`/`bldg2` `has_telemetry:true` |
| STRESS | **PASS** `fully_qualified=true` — `reports/nightly-ot-bench_20260905T181633Z/` (gates 00–08 PASS) |
| ZAP | **PASS** — public baseline High=0 (`ACCEPT_ZAP_MEDIUM=1`) |
| Auth matrix / MCP | **PASS** |
| Overview MQTT `zone_t` charts | closed under Wave B / #851 |
| Path B Lab gate trio | **DEFERRED** (per 3.3.26 plan) |

**Series 3.3.21→3.3.26:** product+qual harness **CLOSED** for 3.3.26 stress. Tip mqtt/fieldbus same-sha **CLOSED** on Wave A. Overview MQTT charts remain **OPEN** for Wave B.

## Verdict — 3.3.25 SV/ECON Lab tuners (2026-09-05) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #844 → `e78a6089`; VERSION **3.3.25** |
| Tip / pin | central/web **`sha-e78a608`** · health **`3.3.25+e78a608934ed`** |
| Shipped | SV-RANGE `range_scale_humidity` / `range_scale_pressure`; ECON-4 `oat_rat_delta_min` |
| Not in this rev (residual) | Broader ECON-2..7 / AHU / VAV / plant Lab gaps → **DEFERRED** → 3.3.26 residual |
| GHCR | central+web OK; mqtt/fieldbus tip sync **DEFERRED** (`sha-b3004aa`) |
| Railway backup | `~/openfdd-backups/railway/20260905T052041Z/` |
| STRESS | **PASS** — `reports/nightly-ot-bench_20260905T052208Z/` |
| ZAP | **PASS** — `reports/zap-railway_20260905T052244Z/` · `FAIL-NEW:0` |

## Verdict — 3.3.24 GL36 Lab tuners (2026-09-05) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #842 → `72b22995`; VERSION **3.3.24** |
| Tip / pin | central/web **`sha-72b2299`** · health **`3.3.24+72b2299541e9`** |
| Shipped | FC2/3/5/8–12 SQL-honest Lab params (`MIX_TOL`, `DELTA_SUPPLY_FAN`, econ/clg thresholds, …); defaults = prior literals |
| GHCR | central+web tags OK; mqtt/fieldbus Publish still slow/hung — **DEFERRED** tip sync |
| Railway backup | `~/openfdd-backups/railway/20260905T034509Z/` |
| Fieldbus | `sha-b3004aa` (prior); `edges:1` |
| STRESS | **PASS** — `reports/nightly-ot-bench_20260905T035119Z/` (first `034632Z` 00 FAIL edges race; re-run PASS) |
| ZAP | **PASS** — `reports/zap-railway_20260905T035155Z/` · `FAIL-NEW:0` |
| Gate trio / mode_delay | **DEFERRED** → 3.3.26 |
| mqtt/fieldbus tip pin | **DEFERRED** |

## Verdict — 3.3.23 Faults/Lab declutter (2026-09-05) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #840 → `40ac0664`; VERSION **3.3.23** |
| Tip / pin | central/web `40ac0664` · **`sha-40ac066`** · health **`3.3.23+40ac06640af4`** |
| GHCR | central + web tags **green**; mqtt + fieldbus Publish hung on multi-arch fieldbus build (runs `33927904427`, `33934657485` cancelled) |
| Railway backup | `~/openfdd-backups/railway/20260905T021711Z/` |
| Hub re-pin | central + web → `sha-40ac066`; mqtt left on `sha-b3004aa` |
| x86 fieldbus | `openfdd_fieldbus_railway_up.sh sha-b3004aa` (prior tip); `edges:1` |
| STRESS 0–6 | **PASS** — `reports/nightly-ot-bench_20260905T021921Z/` |
| ZAP | **PASS** — `reports/zap-railway_20260905T021959Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56` |
| Shipped | Lab default category FC/VAV; `FC*` grouped as family FC; Results/Plots/Overview Run vs Tune vs Update analytics copy |
| **mqtt/fieldbus tip pin sync** | **DEFERRED** → next Publish success or 3.3.24 re-pin (same sha) |
| **bldg2 Overview UI** | **DEFERRED** → 3.3.26 |

## Verdict — 3.3.22 One Dump IA (2026-09-04) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #838 → `b3004aa3`; VERSION **3.3.22** |
| Topology | Railway hub only; bensbench x86 fieldbus MQTTS; **no Pi** |
| Tip / pin | `b3004aa3` · GHCR **`sha-b3004aa`** · health **`3.3.22+b3004aa33bc2`** |
| GHCR publish | **green** — run `33915988499` central/web/mqtt/fieldbus `sha-b3004aa` |
| Railway backup | `~/openfdd-backups/railway/20260904T222234Z/` |
| Railway hub re-pin | central → mqtt → web `sha-b3004aa` |
| x86 fieldbus | `openfdd_fieldbus_railway_up.sh sha-b3004aa`; health `edges:1`; `ingest_ok` advancing |
| STRESS 0–6 | **PASS** — `reports/nightly-ot-bench_20260904T222851Z/` (first attempt `222500Z` FAIL: local `.env` clobbered Railway admin → 401; re-run with Railway `OPENFDD_ADMIN_PASSWORD`) |
| STRESS 6 ZAP | **PASS** (light) — `reports/zap-railway_20260904T222928Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56` |
| Shipped | Nav **Dump**; single dump workflow (no Uploads/Fuel/Twin/ECM radio); ingest via Upload/Sites; Metering package utilities |
| Harness note | Do **not** source local `.env` over Railway admin for hub stress |
| **bldg2 Overview UI** | **DEFERRED** → 3.3.26 |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** |
| WattLab ML depth (#763) | **DEFERRED** (explicit non-goal) |

## Verdict — 3.3.21 Overview / MQTT / Metering closeout (2026-09-04) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #833 → `792ebeec` (plus #835 PayPal polish on tip used for pin); VERSION **3.3.21** |
| Topology | Railway hub only; bensbench x86 fieldbus MQTTS; **no Pi** |
| Field identity | `bldg2` / `pi-1` kit (CA reuse); hosted-weather AV 9101 loopback |
| Tip / pin (closeout) | `792ebeec` · GHCR **`sha-792ebee`** · health **`3.3.21+792ebeec4be3`** |
| Docs tip note | #836 paypal.me + #837 recovery pack later on master — **not** used for closeout pin identity |
| GHCR publish | **green** — central/web/mqtt/fieldbus `sha-792ebee` |
| Railway backup | `~/openfdd-backups/railway/20260904T193732Z/` |
| Railway hub re-pin | central → mqtt → web `sha-792ebee`; central redeploy after mqtt |
| x86 fieldbus | `openfdd_fieldbus_railway_up.sh sha-792ebee`; health `edges:1`; `ingest_ok` advancing |
| STRESS 0 hub + edges | **PASS** — `reports/nightly-ot-bench_20260904T194123Z/` |
| STRESS 1 synth59 | **PASS** — same dir `01_synth59_Railway.log` |
| STRESS 2 gate 17 | **PASS** — `02_gate_17.log` |
| STRESS 3 B100 | **PASS** — `03_B100_Railway-only.log` |
| STRESS 4 Creekside | **PASS** — `04_Creekside.log` |
| STRESS 5 gate 19 | **PASS** — `05_gate_19.log` + `bundle_validate.json` |
| STRESS 6 ZAP | **PASS** (light) — `reports/zap-railway_20260904T194203Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56`. No High/Critical |
| Shipped (product) | Overview readiness A–Z; MQTT Zone Other; Metering package utilities |
| **bldg2 Overview UI** site cleanup | **DEFERRED** → revisit 3.3.26 soft-OPEN |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** |

## Verdict — 3.3.20 x86 fieldbus → Railway hub (2026-09-04) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #831 → `aef6fc1f`; VERSION **3.3.20** |
| Topology | Railway hub only; bensbench x86 fieldbus MQTTS; **no Pi** |
| Field identity | `bldg2` / `pi-1` kit (CA reuse); `config/fieldbus/field_devices.toml` hosted-weather `127.0.0.1` AV 9101 |
| Tip / pin | `aef6fc1f` · GHCR **`sha-aef6fc1`** · health **`3.3.20+aef6fc1f5b29`** (central + web `version.json`) |
| GHCR publish | **green** — central/web/mqtt/fieldbus `sha-aef6fc1` |
| Railway backup | `~/openfdd-backups/railway/20260904T035328Z/` |
| Railway hub re-pin | central → mqtt → web `sha-aef6fc1`; central redeploy after mqtt (ingest resume) |
| x86 fieldbus | `openfdd_fieldbus_railway_up.sh sha-aef6fc1`; MQTTS connected; `/api/edges` `pi-1` `has_telemetry:true` |
| STRESS 0 hub + edges | **PASS** — `reports/nightly-ot-bench_20260904T040851Z/` |
| STRESS 1 synth59 | **PASS 59/59** — `reports/wattlab-parity/artifacts/synthetic_59/` |
| STRESS 2 gate 17 | **PASS** (re-run after Railway admin not clobbered by local `.env`) — `reports/railway-hub-rerun_20260904T041358Z/` |
| STRESS 3 B100 | **PASS** `RAILWAY_ONLY=1` — FC1 **118.42 h**, runtime **1638.75 h**, `has_confirmed_fault:true`, `poll_seconds=300` @ `20260904T040851Z/summary.json` |
| STRESS 4 Creekside | **PASS** fixture + full zip → `LAKESIDE_ES` @ `reports/railway-hub-rerun_20260904T041358Z/` |
| STRESS 5 gate 19 | **PASS READY** — same rerun dir `bundle_validate.json` |
| STRESS 6 ZAP | **PASS** (light) — `reports/zap-railway_20260904T040909Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56`. No High/Critical. Same header residuals as prior cycle |
| Rev template | [`PATCH_CYCLE.md`](PATCH_CYCLE.md) |
| **bldg2 Overview UI** | **DEFERRED** |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** |

Harness note: `RAILWAY_ONLY=1` must keep `RAILWAY_ADMIN_PASSWORD` after sourcing local `.env` (`lib.sh` + Creekside spot).

## Verdict — 3.3.19 utilities/export train (plan name 3.3.20, 2026-09-03) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #827 → `15baccf8`; VERSION **3.3.19**; #828 gate-19 shell; #829 agent/ops handbooks |
| Tip / pin | `0c1029da` · GHCR **`sha-0c1029d`** · health **`3.3.19+0c1029da60c7`** (local + Railway) |
| GHCR publish | **green** on tip — central/web/mqtt/fieldbus `sha-0c1029d` (nightly digest match on gate 00) |
| Railway backup | `~/openfdd-backups/railway/20260903T175358Z/` (`central-workspace.tgz` + mqtt certs) |
| Railway hub re-pin | central → mqtt → web `sha-0c1029d`; central redeploy after mqtt (ingest resume) |
| Local re-pin | `.env` `OPENFDD_IMAGE_TAG=sha-0c1029d`; `openfdd_maint_update_resume.sh react-ot sha-0c1029d --skip-maintenance` |
| bosspi fieldbus | arm64 `sha-0c1029d` (bench `docker save` load — Pi GHCR DNS timeout); `zone_other`; MQTTS connected `edge:bldg2:pi-1` |
| Pipeline A | **PASS** — `/api/health` `edges:1` `ingest_ok` advancing; `/api/edges` `pi-1` `has_telemetry:true` |
| Smoke 01/06/10/18 | **PASS** inside `run_all` + gate 18 `reports/nightly-ot-bench_20260903T180949Z/` |
| STRESS 1 `run_all` | **PASS** gates **00–16** @ `reports/nightly-ot-bench_20260903T180949Z/` (`unset SKIP_PULL`, `WEATHER_SOAK_SECS=120`). First pass gate **12 FAIL** (harness still expected 66); re-run **PASS** after registry total **68** (UTIL-MONTHLY/INTERVAL) |
| STRESS 2 synth59 | **PASS 59/59** — `reports/wattlab-parity/artifacts/synthetic_59/` |
| STRESS 3 gate 17 | **PASS** — health matrix + overview (`RUN_SYNTH59_HEALTH_MATRIX=1` in nightly `20260903T180949Z`) |
| STRESS 4 B100 | **PASS** — `reports/railway-b100-parity_20260903T182530Z/summary.json` (also copied in nightly dir). FC1 **118.42 h**, runtime **1638.75 h**, `has_confirmed_fault:true`, `poll_seconds=300` local ≡ Railway |
| STRESS 5 Creekside | **PASS** fixture + **full** `/home/ben/OpenFdd_Creekside.zip` → `LAKESIDE_ES` @ `reports/creekside-package-import_20260903T182802Z/` |
| STRESS 6 gate 19 | **PASS READY** — `reports/nightly-ot-bench_20260903T182826Z/bundle_validate.json` |
| STRESS 7 ZAP | **PASS** (light) — `reports/zap-railway_20260903T182838Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56`. No High/Critical. Accepted residuals: missing CSP / X-Frame-Options / SRI (Medium); HSTS/X-CTO/Permissions-Policy/COOP/COEP (Low); cache + plotly timestamp (Info) |
| Utilities / Export UI | `utilities_v1`; `UTIL-MONTHLY`/`UTIL-INTERVAL`; `/export`; fuel ZIP upload removed |
| **bldg2 Overview UI** | **DEFERRED** |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** — STRESS 7 is unauthenticated baseline only |

**Issues closed (foundation):** [#763](https://github.com/bbartling/open-fdd/issues/763), [#805](https://github.com/bbartling/open-fdd/issues/805) — do not reopen. ML/vibe20 depth deferred.

## Verdict — 3.3.19 remaining bugs + stress (2026-09-02) — CLOSED

| Check | Evidence |
|-------|----------|
| GHCR publish | **green** on `b565d78d` — images `sha-b565d78` |
| Railway backup | `~/openfdd-backups/railway/20260902T145413Z/` |
| Railway hub re-pin | central→mqtt→web `sha-b565d78`; health `3.3.18+b565d78d2cae` |
| Local + bosspi re-pin | `openfdd_maint_update_resume.sh react-ot sha-b565d78`; bosspi fieldbus `sha-b565d78` arm64 |
| bosspi `zone_other` | `OPENFDD_EQUIPMENT_TYPE=zone_other` in `compose.edge.local.yml` (ops, not committed) |
| Pipeline A | **PASS** — `/api/edges` → `pi-1`/`bldg2` `has_telemetry:true` @ `sha-b565d78` |
| Smoke gates | **PASS** — 01/06/10/18 (`reports/nightly-ot-bench_20260902T145608Z/` gate 18) |
| **`run_all` stress** | **PASS** — `reports/nightly-ot-bench_20260902T145737Z/` gates **00–16** (`unset SKIP_PULL`, `WEATHER_SOAK_SECS=120`) |
| Synthetic-59 target pairs | **PASS** — 59/59 @ `reports/wattlab-parity/artifacts/synthetic_59/` |
| Gate 17 health matrix | **PASS** — `RUN_SYNTH59_HEALTH_MATRIX=1` (`ofdd_health_matrix_fault_hours_checks.json`, `ofdd_overview_analytics_checks.json`) |
| BUILDING_100 Railway vs local | **PASS** — `reports/railway-b100-parity_20260902T151009Z/` (FC1 **118.42 h**, runtime **1638.75 h**, series `has_confirmed_fault:true`, `poll_seconds=300`) |
| **bldg2 Overview UI** | **DEFERRED** — env + Pipeline A verified; SPA Zone Other shells need operator browser sign-off |
| BUILDING_50 / AFDD flood | **DEFERRED** — no package on bench (operator skip) |

**Harness added:** `scripts/gates/railway_b100_parity_spot.sh` (local + Railway API capture + `summary.json`).

## Verdict — 3.3.18 nightly refresh (2026-09-02)

| Check | Evidence |
|-------|----------|
| **#821** merged | `002b0563` — 3.3.17 `recreate_bench_fieldbus` before OT gates |
| **#822** merged | `0e5a9b16` — 3.3.18 gate 03 ingest honesty |
| GHCR Publish | **green** on `ca677075` — images `sha-ca67707` |
| Railway backup | `~/openfdd-backups/railway/20260902T120941Z/` |
| Railway hub re-pin | central→mqtt→web `sha-ca67707`; health `3.3.18+ca677075752d` |
| Local container refresh | `openfdd_maint_update_resume.sh react-ot sha-ca67707` (post docker maintenance) |
| bosspi fieldbus re-pin | `sha-ca67707` arm64; MQTTS `reseau.proxy.rlwy.net:44763` |
| Local `run_all` stress | **PASS** — `reports/nightly-ot-bench_20260902T125016Z/` gates **01–16** (`SKIP_PULL=1`, `WEATHER_SOAK_SECS=120`) |
| `run_all` with GHCR pull | gate **00 pull PASS** — `20260902T123715Z/`; gate 01 fixed in **#824** merged |
| Gate 18 volume restore | **PASS** — `reports/nightly-ot-bench_20260902T124850Z/` (ingest_ok reset accepted when volume data preserved) |
| Phase 2 bench hygiene | **CLOSED** — #821 fieldbus refresh, #822 gate 03 honesty |
| **bldg2 Overview** | **DEFERRED** — `OPENFDD_EQUIPMENT_TYPE=zone_other` + UI sign-off |
| Railway F1 pipeline | **PARTIAL** — BUILDING_100 FC1 **PASS**; FDD/series spot-check + full parity in 3.3.19; BUILDING_50/AFDD **DEFERRED** |
| BUILDING_100 local vs Railway | **PASS** — FC1 AHU_1 **118.42 h** Railway @ `sha-ca67707`; artifact `reports/railway-f1-spot_20260902T124900Z/` |

## Verdict — 3.3.18 closeout (2026-09-02 early)

| Check | Evidence |
|-------|----------|
| Local `run_all` (harness-only pin) | **PASS** — `reports/nightly-ot-bench_20260902T013750Z/` gates **01–16** on `sha-3e35b2d` images |

## BUILDING_100 — local vs Railway parity (2026-09-02 @ sha-b565d78)

| Field | Local | Railway | Tolerance |
|-------|-------|---------|-----------|
| FC1 AHU_1 `fault_hours` | 118.42 h | 118.42 h | ±0.05 h |
| AHU_1 `run_hours` | 1638.75 h | 1638.75 h | ±0.01 h |
| `poll_seconds` | 300 | 300 | exact |
| `fdd/series` `has_confirmed_fault` | true | true | exact |

**Artifact:** `reports/railway-b100-parity_20260902T151009Z/` (prior `reports/railway-b100-parity_20260901T190000Z/`, spot `reports/railway-f1-spot_20260902T124900Z/`).

## BUILDING_100 — local vs Railway parity (2026-09-02 @ sha-ca67707)

| API | Railway (`sha-ca67707`) |
|-----|-------------------------|
| `POST /api/fdd/run` FC1 AHU_1 | FAULT **118.42 h** |
| `poll_seconds` | 300 |
| Hub health | `edges:1`, `ingest_ok` advancing |

**Artifact:** `reports/railway-f1-spot_20260902T124900Z/` (prior parity `reports/railway-b100-parity_20260901T190000Z/`).

## Dual pipeline

| Pipeline | Status |
|----------|--------|
| **Railway hub + x86 field** (3.3.20+) | **PASS** @ `sha-aef6fc1` — hosted-weather loopback → MQTTS; Pis removed from stress |
| **A Cloud** bosspi → Railway (historical) | **PASS** last @ `sha-0c1029d` — **retired** for closeout |
| **B Local** react-ot (historical) | **PASS** last `20260903T180949Z` — **lab only**, not closeout |

## Patch cycle — Phase 7 + phase2 bench hygiene (2026-09-01 → 2026-09-02)

| Gate / ID | Symptom | Status on tip harness |
|-----------|---------|------------------------|
| **#528** poll_seconds | harness `poll_seconds=300` | **PATCHED 3.3.16** — gate 06 `poll_seconds≈60` on CSV fixture |
| **fieldbus-poll-stale** | `points_polled:0` after long sessions | **PATCHED 3.3.17** — `recreate_bench_fieldbus` |
| **gate03-ingest-counter** | ingest counter unchanged despite live MQTTS | **PATCHED 3.3.18** |
| **playwright-workflows** | `/rules` redirect + auth timing | **PATCHED 3.3.16** — #818 |
| **gate01-fieldbus-starting** | gate 01 FAIL after fieldbus recreate (`health=starting`) | **PATCHED harness** — #824 merged |
| **gate18-ingest-counter** | gate 18 FAIL on ingest_ok reset after central recreate | **PATCHED harness** — #824 merged |
| **weather-legitimacy** | Chicago Δ>3°F on short soak | **OPEN** tier-C — passed on short soak runs |

**Artifacts:**

| Pin | Artifact | Result |
|-----|----------|--------|
| `sha-b565d78` | `reports/nightly-ot-bench_20260902T145737Z/` | **PASS** gates 00–16 (pull + stress) |
| `sha-b565d78` | `reports/railway-b100-parity_20260902T151009Z/` | **PASS** B100 Railway vs local |
| `sha-b565d78` | `reports/wattlab-parity/artifacts/synthetic_59/` | **PASS** synthetic-59 59/59 + gate 17 |
| `sha-ca67707` | `reports/nightly-ot-bench_20260902T125016Z/` | **PASS** gates 01–16 |
| `sha-ca67707` | `reports/nightly-ot-bench_20260902T123715Z/` | gate 00 pull PASS; gate 01 FAIL (pre-harness fix) |
| `sha-3e35b2d` | `reports/nightly-ot-bench_20260902T013750Z/` | **PASS** gates 01–16 (harness on old images) |

## Railway F1 pipeline (separate tier — BUILDING_100 closed)

| Check | Last evidence |
|-------|---------------|
| Hub health | `3.3.18+b565d78d2cae`, `edges:1`, `ingest_ok` advancing |
| **BUILDING_100 FC1 + series + runtime** | **PASS** 2026-09-02 @ `sha-b565d78` — `reports/railway-b100-parity_20260902T151009Z/` |
| FDD run + series spot-check | **PASS** — `railway_b100_parity_spot.sh` (not rule_id DF55) |
| BUILDING_50 CSV import + FDD | **DEFERRED** — no package on bench |
| AFDD flood | **DEFERRED** — operator skip |
| bldg2 Overview UI | **DEFERRED** — `OPENFDD_EQUIPMENT_TYPE=zone_other` + Pipeline A; SPA browser sign-off pending |

Local bench `run_all` green does **not** require Railway F1 in the same session.

## Data restore across patch / nightly re-pin (2026-09-01)

**Model:** durability = **same volume**, not a per-message backup file.

| Data class | Where it lives | Survives image re-pin? |
|------------|----------------|------------------------|
| **CSV / package import** | `workspace/data/csv_buildings/` + Parquet | **Yes** — bind-mount |
| **MQTT stream (live OT)** | `openfdd/history/…/part-*.parquet` | **Yes** |
| **`ingest_ok` counter** | Process/runtime | **Resets** on recreate — use MQTTS + Parquet proof |

**Gate 18 PASS:** `reports/nightly-ot-bench_20260902T124850Z/` (harness accepts ingest_ok reset)

Script: `scripts/nightly-ot-bench/18_volume_restore_smoke.sh`

## Soft-OPEN / follow-up

Triage refreshed **2026-09-12** for Wave M kickoff. Historical Wave D–G items below are dispositioned against later CLOSED evidence (do not treat as current OPEN bugs).

| ID | Disposition | Notes |
|----|-------------|-------|
| **mqtt-ingest-stall** | **CLOSED** (3.3.34 / Wave D) | #860 · tip `sha-9aebf42` · smoke `reports/waveD_railway_smoke_20260906T173032Z/` |
| **bldg2-overview-signoff** | **CLOSED** (Wave H) | #868/#869 · Inspect/RCx points>0; Overview auto-load |
| **railway-f1-stress** | **CLOSED** (B100) / **DEFERRED** (B50) / **IN Wave M M5** (AFDD flood gate 12) | B100 PASS retained; B50 package still deferred; AFDD flood required at M5 (budgeted, isolated-candidate default) |
| **weather-legitimacy-chicago** | **DEFERRED** | Full soak optional; short soak historically green |
| **railway-ui-fdd-stale** | **CLOSED** (Wave E / tip UX) | Building-scoped FDD chrome on tip |
| **local-parquet-root-split** | **CLOSED** (Wave M D2 / 3.5.7) | Rule results under parquet/workspace; readiness fails ephemeral prod paths |
| **lake-credential-rotation** | **CLOSED** | Ops hygiene; session-env only |
| **deploy-mqtt-acl-mount** | **CLOSED** | Documented ops note; file-not-dir |
| **vibe19-operational-gate-lab** | **CLOSED** (3.3.37 / Wave G / #864) | Real SQL/session binding |
| **mqtt-fieldbus-tip-pin-sync** | **CLOSED** (3.3.33+) | Same-sha tip pin law retained |
| **mqtt-overview-spa-parity** | **CLOSED** (3.3.33) | Overview MQTT=CSV historian parity |
| **isolated-authenticated-zap-af** | **CLOSED** (Wave C harness) | Disposable AF+OpenAPI; field closeout public baseline |
| **qualification-viewer-login** | **CLOSED** (3.3.28) | `OPENFDD_VIEWER_PASSWORD` on Railway |
| **hybrid-ml-physics-ahu-vav** | **ABANDONED** | Replaced by lab-tuner-vibe19-parity |
| **sql-anomaly-screening** | **LIVE-lab** (Wave M M2 / 3.5.7) | Lab flag + status API |
| **lab-tuner-vibe19-parity** | **CLOSED** (3.3.37 / Wave G) | #864 · tip `sha-a40787b` · stress `20260907T183808Z` |
| **mqtt-monitor-sse-782** | **CLOSED** (Wave M M1 / 3.5.7) | Central JWT SSE; no browser→Mosquitto WS |
| **wave-m-durable-results** | **IN 3.5.7** (Wave M Track D) | Persistence + auto-results + release orchestrator; M5 stress pending |


## Series wrap draft — Lab tuners 3.3.21→3.3.26

| Metric | 3.3.21 hub | 3.3.26 tip (product) |
|--------|------------|----------------------|
| Dump IA | pre | shipped **3.3.22** |
| Faults Lab declutter | pre | shipped **3.3.23** |
| GL36 Lab tuners | pre | shipped **3.3.24** |
| SV/ECON Lab tuners | pre | shipped **3.3.25** (partial wave) |
| Operational-gate Lab trio | no | **DEFERRED** (no honest SQL binding) |
| Qualification harness | shallow SUMMARY | **3.3.26** manifest + ZAP honesty + auth matrix + Railway MCP |
| Vibe19 UI reference | ~414 | ~414 (not a hard success target) |

## Railway hub inventory

| Role | Service |
|------|---------|
| central | `openfdd-central-cQ-F` |
| mqtt | `openfdd-mqtt` |
| web | `openfdd-web` → https://openfdd-web-production-af99.up.railway.app |

## Ops notes

1. Backup before every central re-pin.  
2. Re-pin order: central → mqtt → web, then `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` on this x86 host.  
3. After mqtt/central redeploy: `railway redeploy -s openfdd-central-cQ-F` if `edges:0` persists.  
4. Do **not** bring local `react-ot` or Raspberry Pi fieldbus back for closeout.  
5. Full stress **LAST**: `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` (CSV synth59 + gate 17 + B100 `RAILWAY_ONLY=1` + Creekside + gate 19 + light ZAP).  
6. `OPENFDD_PARQUET_ROOT=/workspace/openfdd` on Railway when `STORAGE_URL=file:///workspace/openfdd`.
