# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-29  
**Platform:** `3.3.8` / `sha-9667888` (`3.3.8+96678888d875`)  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only (`linux/arm64`)  
**Artifacts:** `reports/patch338_20260829T152852Z/`

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)  
**On GitHub (master tip):** https://github.com/bbartling/open-fdd/blob/master/docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-9667888` | match (digest equal) | `96678888d875…` | `3.3.8+96678888d875` |
| bosspi | fieldbus edge only | `openfdd-fieldbus:sha-9667888` **linux/arm64** | tip rev match | `96678888d875…` | fieldbus healthy |

Prefer `OPENFDD_IMAGE_TAG=sha-<7>` — do not trust sticky `:nightly` without digest check.

## Confirmed PASS

| Gate / check | Result |
|------|--------|
| `00_pull_ghcr_up` react-ot | **PASS** — pin `sha-9667888` |
| `01_health_gates` | **PASS** |
| `combined_ot_synth_validate` | **PASS** (OT Who-Is/RP/poll + MQTT ingest + Modbus + Haystack + synth matrix) |
| `07_cloud_sim` (Pi) | **PASS** — Pi `mqtt_publish_interval=60`, multi-site edges lab+bldg2 |
| `10_dual_mqtt_signoff` `DUAL_MQTT_WAIT_SECS=600` | **PASS** |
| `11_bacnet_pcap_fp_scan` | **PASS** — clean FP scan |
| BUILDING_100 UI smoke | **PASS** — Actions during analytics; economizer/runtime/mech-cool/bas-vs-web-oat; FDD series FC1 (5000 overlay hits); SPA `/` `/actions` `/plot` |

## Dual-site MQTT (lab + bldg2)

| Check | lab / fieldbus-1 | bldg2 / pi-1 |
|-------|------------------|--------------|
| Fieldbus platform | linux/amd64 (bench) | linux/arm64 (Pi) |
| Fieldbus tip | `sha-9667888` rev `96678888d875` | `sha-9667888` rev `96678888d875` |
| Ingest / telemetry span | 10 numeric lines, span≈540s | 10 numeric lines, span≈540s |
| Edges after dual wait | `has_telemetry=true` | `has_telemetry=true` |
| Ingest after dual | `ingest_ok` 39→59 (no dup/reject) | (same central) |

## BUILDING_100 UI (FDD Plots / Actions)

| Check | Result |
|------|--------|
| Overview → Actions while analytics running | **PASS** (HTTP 200, no 401) |
| FDD Plots AHU_1 / FC1 | **PASS** (`/api/fdd/series?rule_id=FC1`, 5000 overlay hits) |
| RCx economizer / runtime / mech-cool / bas-vs-web-oat | **PASS** |

## BACnet pcap

| Check | Result |
|------|--------|
| Capture tool | privileged docker `tcpdump` + rusty-bacnet decode |
| Decode / FP scan vs bad_rusty_bacnet_app | **PASS** — `whois=0`, `ephemeral_whois=0`, `read_property=32`, findings=[] |

## This cycle (3.3.8) — CLOSED

| ID | Finding | Resolution |
|----|---------|------------|
| coderabbit-storage | Package-ingest / analytics ignored `OPENFDD_STORAGE_URL` | **CLOSED** — `fdd_store::local_file_root_from_env()` prefers `OPENFDD_STORAGE_URL` (#797) |
| bench-field-devices | Tip checkout resets OT `field_devices.toml` | **CLOSED** — `ensure_bench_field_devices()` in nightly lib + combined preflight (#797) |
| railway-web-resolver | Railway web crash: bare IPv6 resolver `fd12::10` | **CLOSED in tip image** — nginx entrypoint brackets IPv6 / prefers IPv4 (#797). **Operator:** re-pin Railway central/mqtt/web to `sha-9667888`, set `OPENFDD_NGINX_RESOLVER=auto` (clear interim `[fd12::10]`), verify public SPA + `/api/health` |

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
- Railway hub re-pin to tip is operator/CLI follow-up (no `RAILWAY_TOKEN` on bensbench this cycle).
- Next product fix after 3.3.8 closeout → bump `3.3.8` → `3.3.9`, wait GHCR, re-pin both hosts to the same `sha-*`.
