# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-29  
**Platform:** `3.3.7` / `sha-3395551` (`3.3.7+33955515540e`)  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only (`linux/arm64`)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-3395551` | fieldbus digest match | `33955515540e` | central `3.3.7+33955515540e` |
| bosspi | fieldbus edge only | `openfdd-fieldbus:sha-3395551` **linux/arm64** | same tip | `33955515540e` | fieldbus ok; `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60` |

Prefer `OPENFDD_IMAGE_TAG=sha-<7>` — do not trust sticky `:nightly` without digest check.

## Confirmed PASS

| Gate / check | Result |
|------|--------|
| Combined OT + synth-59 health-matrix | **PASS** (BACnet 15/15 after bench `field_devices` restore; MQTT ingest live; synth 0 fails) |
| Cloud-sim `07` (Pi tip + env instance 600000) | **PASS** (23 pass / 0 fail; override logs `mqtt_publish_interval=60`) |
| Dual MQTT 600s | **PASS** (lab+bldg2 numeric 10/10, span≈540s, ratio≥0.5; ingest 25→45) |
| BACnet pcap FP scan | **PASS** (ReadProperty-heavy, no Who-Is storm) |
| BUILDING_100 UI smoke | **PASS** (Actions no 401; analytics; RCx economizer; FC1 series ok/0 pts WARN) |

## Dual-site MQTT (lab + bldg2)

| Check | lab / fieldbus-1 | bldg2 / pi-1 |
|-------|------------------|--------------|
| Fieldbus platform | linux/amd64 (bench) | linux/arm64 |
| Fieldbus tip | `sha-3395551` / `33955515540e` | `sha-3395551` / `33955515540e` |
| Ingest / telemetry span | MQTTS 10 numeric / ~540s | MQTTS 10 numeric / ~540s (parity **without** hand-edit — baked in `07_cloud_sim`) |

## BUILDING_100 UI (FDD Plots / Actions)

| Check | Result |
|------|--------|
| Overview → Actions while analytics running | **PASS** (200, no 401) |
| FDD Plots AHU_1 / FC1 | **PASS** API (`ok`); series points=0 WARN (same as prior tip when empty window) |
| RCx economizer regression | **PASS** (200, rows=2, points=4000) |

## BACnet pcap

| Check | Result |
|------|--------|
| Capture tool | privileged docker `tcpdump` + rusty-bacnet decode |
| Decode / FP scan vs bad_rusty_bacnet_app | **PASS** (`read_property=32`, `whois=0`, findings=[]) |

## Open findings (future patch cycles)

| ID | Finding | Status |
|----|---------|--------|
| H10 | Large historian quals | **OPEN** |
| dependabot-thrift | Sticky Dependabot thrift updates fail on master | **OPEN** (non-product) |
| issue-763-ml | Engineering bundle phases 2–8 (ML features, splits, UI rename) | **OPEN** |
| coderabbit-storage | Deferred package-ingest full `OPENFDD_STORAGE_URL` layout | **OPEN** |
| lint-sweep | Remaining allow/expect outside scoped pass | **OPEN** |
| bench-field-devices | Tip checkout resets committed example `field_devices.toml`; restore from local overlay before OT poll gates | **OPEN** (ops hygiene) |

## Hygiene

- Patch-cycle train: blank → tip soak → fill this report. Agent law: [`openfdd_agent_spec/`](../../openfdd_agent_spec/) ([`docs/RUST_LINT_HYGIENE.md`](../../openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md)).
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
- Anti-hardcoding: no private OT IPs in this report.
- No stale PRs / feature branches after each tiny rev bump.
- Product fix this cycle: gate10-pi-mqtt-interval closed via `07_cloud_sim` Pi override bake (#795).
- Next product fix → bump `3.3.7` → `3.3.8`, wait GHCR, re-pin both hosts to the same `sha-*`.
- Artifacts: `reports/patch337_20260829_020507/`. Stacks left running on `sha-3395551`.
