# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** _(fill after tip soak)_  
**Platform:** `3.3.8` / `sha-_______` _(pin after GHCR publish)_  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only (`linux/arm64`)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)  
**On GitHub (master tip):** https://github.com/bbartling/open-fdd/blob/master/docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md

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

## This cycle (3.3.8) — in flight

| ID | Finding | Notes |
|----|---------|--------|
| coderabbit-storage | Package-ingest / analytics ignore `OPENFDD_STORAGE_URL` | Prefer storage URL over legacy `OPENFDD_PARQUET_ROOT` |
| bench-field-devices | Tip checkout resets OT `field_devices.toml` | Auto-restore from `.local` / bench example before OT gates |
| railway-web-resolver | Railway web crash: `invalid port in resolver "fd12::10"` | Bracket IPv6 / prefer IPv4 in `OPENFDD_NGINX_RESOLVER=auto` |

## Open findings (deferred — future cycles)

| ID | Finding | Notes | Pointer |
|----|---------|-------|---------|
| **H10** | Large historian scale / release quals | Multi-cycle program; not a tiny-rev | [`HISTORIAN_PROGRAM.md` §H10](../../openfdd_agent_spec/HISTORIAN_PROGRAM.md); [`HISTORIAN_SCALE_QUALIFICATION.md`](./HISTORIAN_SCALE_QUALIFICATION.md) |
| **issue-763-ml** | Engineering bundle phases 2–8 | ML features/labels/splits, exports, WattLab→Engineering rename | [#763](https://github.com/bbartling/open-fdd/issues/763) |
| **dependabot-thrift** | Sticky Dependabot thrift updates fail on master | **Non-product** — dismiss until DataFusion/Arrow drop thrift | [`thrift-advisory.md`](../security/thrift-advisory.md) |
| **lint-sweep** | Remaining `#[allow]` / `#[expect]` outside scoped passes | **Hygiene** — scoped sweeps only per agent law | [`RUST_LINT_HYGIENE.md`](../../openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md) |

## Hygiene

- Patch-cycle train: blank → tip soak → fill this report. Agent law: [`openfdd_agent_spec/`](../../openfdd_agent_spec/).
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
- Anti-hardcoding: no private OT IPs in this report.
- No stale PRs / feature branches after each tiny rev bump.
- This report is **open-fdd only** (not vibe_code_apps_13).
- Next product fix after 3.3.8 closeout → bump `3.3.8` → `3.3.9`, wait GHCR, re-pin both hosts to the same `sha-*`.
