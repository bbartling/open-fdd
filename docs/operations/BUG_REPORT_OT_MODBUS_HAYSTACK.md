# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-28  
**Platform:** `3.3.6` / `sha-aac593c`  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only (`linux/arm64`)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-aac593c` | explicit pin (not sticky nightly) | `aac593c19833` | `3.3.6+aac593c19833` |
| bosspi | fieldbus edge only | `openfdd-fieldbus:sha-aac593c` **linux/arm64** | matches bench pin | `aac593c19833` | fieldbus `/health` ok |

Prefer `OPENFDD_IMAGE_TAG=sha-aac593c` — do not trust sticky `:nightly` without digest check.

GHCR publish: workflow run **33186905614** success for merge `aac593c` (#793).

## Confirmed PASS

| Gate / check | Result |
|------|--------|
| `combined_ot_synth_validate.sh` | **PASS** — BACnet OT, MQTT persist, Modbus, Haystack, suspend/resume, synthetic CSV bulk |
| `07_cloud_sim.sh` | **PASS** — multi-site central `OPENFDD_SITE_ID=+`, Pi arm64 edge 600000, Who-Is 599999+600000 |
| `10_dual_mqtt_signoff.sh` (600s, retry after Pi `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60`) | **PASS** — rev match, lab+bldg2 telemetry, count+span parity, ingest growth |
| `11_bacnet_pcap_fp_scan.sh` | **PASS** — docker tcpdump + rusty-bacnet decode; 30 ReadProperty, no FP storm |
| UI smoke BUILDING_100 | **PASS** — JWT login; analytics POSTs + immediate `/api/actions` HTTP 200 (no 401); FC1 `/api/fdd/series` ok (5000 rows, roles mapped); RCx economizer 4000 points |
| Stack left running | **PASS** — react-ot + Pi edge on `sha-aac593c` |
| Closeout live MQTT peek (~90s) | **PASS** — lab + bldg2 numeric telemetry both present (`reports/patch336_live_205929/`) |
| Container health closeout | **PASS** — central/fieldbus healthy; both edges `has_telemetry=true`; 0 open PRs / no `feat/*`\|`fix/*` remotes |

Artifacts: `reports/patch336_20260828_201214/` (+ live peek `reports/patch336_live_205929/`).

## Dual-site MQTT (lab + bldg2)

| Check | lab / fieldbus-1 | bldg2 / pi-1 |
|-------|------------------|--------------|
| Fieldbus platform | bench amd64 | **linux/arm64** |
| Fieldbus tip | `sha-aac593c` / `aac593c19833` | same OCI rev |
| Ingest / telemetry span | 10 msgs / 540s span | 10 msgs / 540s span (after Pi 60s publish interval) |

Note: first dual-MQTT attempt failed count parity (lab 10 vs bldg2 2) because Pi edge lacked `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60`; fixed in `compose.edge.local.yml` on bosspi before retry.

## BUILDING_100 UI (FDD Plots / Actions)

| Check | Result |
|------|--------|
| Overview → Actions while analytics running | **PASS** — `/api/actions` 200 during parallel analytics POSTs |
| FDD Plots AHU_1 / FC1 | **PASS** — `GET /api/fdd/series?equipment_id=AHU_1&rule_id=FC1&building_id=BUILDING_100` ok, 5000 rows, no unmapped roles |
| RCx economizer regression | **PASS** — `/api/analytics/economizer` rows=2, points=4000 |

## BACnet pcap

| Check | Result |
|------|--------|
| Capture tool | privileged docker `tcpdump` + rusty-bacnet decode |
| Decode / FP scan vs bad_rusty_bacnet_app | **PASS** — 30 ReadProperty, 0 Who-Is storm / ephemeral broadcast findings |

## Open findings (future patch cycles)

| ID | Finding | Status |
|----|---------|--------|
| H10 | Large historian quals | **OPEN** |
| dependabot-thrift | Sticky Dependabot thrift updates fail on master | **OPEN** (non-product) |
| issue-763-ml | Engineering bundle phases 2–8 (ML features, splits, UI rename) | **OPEN** |
| coderabbit-storage | Deferred package-ingest full `OPENFDD_STORAGE_URL` layout | **OPEN** |
| lint-sweep | Remaining allow/expect outside scoped pass | **OPEN** |
| gate10-pi-mqtt-interval | `07_cloud_sim` should set `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60` on Pi edge by default (bench local override already has it) | **OPEN** (ops doc only this cycle) |

## Hygiene

- Patch-cycle train: blank → tip soak → fill this report. Agent law: [`openfdd_agent_spec/`](../../openfdd_agent_spec/) ([`docs/RUST_LINT_HYGIENE.md`](../../openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md)).
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
- Anti-hardcoding: no private OT IPs in this report.
- No stale PRs / feature branches after each tiny rev bump.
- Next product fix → bump `3.3.6` → `3.3.7`, wait GHCR, re-pin both hosts to the same `sha-*`.
