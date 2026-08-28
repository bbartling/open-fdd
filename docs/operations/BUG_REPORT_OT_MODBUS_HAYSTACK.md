# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** _(fill after tip soak)_  
**Platform:** `3.3.6` / `sha-_______` _(pin after GHCR publish)_  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only (`linux/arm64`)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-_______` | | | |
| bosspi | fieldbus edge only | `openfdd-fieldbus:sha-_______` **linux/arm64** | | | |

Prefer `OPENFDD_IMAGE_TAG=sha-<7>` — do not trust sticky `:nightly` without digest check.

## Confirmed PASS

| Gate / check | Result |
|------|--------|
| _(blank — fill after dual MQTT / synthetic / pcap / UI smoke)_ | |

## Dual-site MQTT (lab + bldg2)

| Check | lab / fieldbus-1 | bldg2 / pi-1 |
|-------|------------------|--------------|
| Fieldbus platform | | |
| Fieldbus tip | | |
| Ingest / telemetry span | | |

## BUILDING_100 UI (FDD Plots / Actions)

| Check | Result |
|------|--------|
| Overview → Actions while analytics running | _(pending)_ |
| FDD Plots AHU_1 / FC1 | _(pending)_ |
| RCx economizer regression | _(pending)_ |

## BACnet pcap

| Check | Result |
|------|--------|
| Capture tool | privileged docker `tcpdump` + rusty-bacnet decode |
| Decode / FP scan vs bad_rusty_bacnet_app | _(pending)_ |

## Open findings (future patch cycles)

| ID | Finding | Status |
|----|---------|--------|
| H10 | Large historian quals | **OPEN** |
| dependabot-thrift | Sticky Dependabot thrift updates fail on master | **OPEN** (non-product) |
| issue-763-ml | Engineering bundle phases 2–8 (ML features, splits, UI rename) | **OPEN** |
| coderabbit-storage | Deferred package-ingest full `OPENFDD_STORAGE_URL` layout | **OPEN** |
| lint-sweep | Remaining allow/expect outside scoped pass | **OPEN** |

## Hygiene

- Patch-cycle train: blank → tip soak → fill this report. Agent law: [`openfdd_agent_spec/`](../../openfdd_agent_spec/) ([`docs/RUST_LINT_HYGIENE.md`](../../openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md)).
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
- Anti-hardcoding: no private OT IPs in this report.
- No stale PRs / feature branches after each tiny rev bump.
- Next product fix → bump `3.3.6` → `3.3.7`, wait GHCR, re-pin both hosts to the same `sha-*`.
