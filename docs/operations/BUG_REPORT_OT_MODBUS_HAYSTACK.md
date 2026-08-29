# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-29  
**Platform:** `3.3.9` / `sha-TBD` (bump in flight; baseline was `3.3.8` / `sha-9667888`)  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`Host bosspi` / `CLOUD_SIM_PI_SSH`) — fieldbus only (`linux/arm64`)  
**Artifacts:** prior `reports/patch338_20260829T152852Z/`; this cycle TBD  
**Train:** continuous tiny-rev until bosspi → Railway stream healthy — plan [`patch_cycle_3.3.9_railway_web_api`](../../../.cursor/plans/patch_cycle_3.3.9_railway_web_api.plan.md)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)  
**On GitHub (master tip):** https://github.com/bbartling/open-fdd/blob/master/docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | (ops host; stack optional) | TBD after 3.3.9 Publish | TBD | TBD | TBD |
| Railway hub | central / mqtt / web | TBD `sha-*` after Publish | TBD | TBD | TBD |
| bosspi | fieldbus edge only | was `sha-9667888` arm64 healthy; re-pin after tip | TBD | TBD | TBD |

Prefer `OPENFDD_IMAGE_TAG=sha-<7>` — do not trust sticky `:nightly` without digest check.

## Confirmed PASS (historical — 3.3.8 bench soak)

| Gate / check | Result |
|------|--------|
| `00_pull_ghcr_up` react-ot | **PASS** — pin `sha-9667888` |
| `01_health_gates` | **PASS** |
| `combined_ot_synth_validate` | **PASS** |
| `07_cloud_sim` (Pi) | **PASS** — `mqtt_publish_interval=60` |
| `10_dual_mqtt_signoff` | **PASS** (historical bench; **not** 3.3.9 cloud gate) |
| `11_bacnet_pcap_fp_scan` | **PASS** |
| BUILDING_100 UI smoke | **PASS** |

## This cycle (3.3.9) — OPEN / in progress

| ID | Finding | Status | Next |
|----|---------|--------|------|
| **railway-web-api-double-path** | `/api/*` empty 404 via variable `proxy_pass …/api/` | **FIX SHIPPING** in 3.3.9 nginx | CLOSE when public `/api/health` 200 on tip web |
| **railway-mqtt-certs** | mqtt Crashed; no `/mosquitto/certs`; `volumes: []` | **OPEN** ops | Volume + upload PEMs → Online |
| **bosspi-railway-mqtt** | Pi → Railway MQTTS not yet | **OPEN** | After L1+L3 |
| **railway-stream-health** | Hub/stream container health | **OPEN** | After L4 |
| **railway-fdd-zn-duct** | FDD on bosspi stream | **OPEN** | After stream healthy |
| **bench-stack-down** | react-ot exited 137 | **OPEN** non-blocking | Optional local restore |

## Prior cycle (3.3.8) — CLOSED

| ID | Resolution |
|----|------------|
| coderabbit-storage | **CLOSED** #797 |
| bench-field-devices | **CLOSED** #797 |
| railway-web-resolver | **CLOSED** tip image #797 (web Online; SPA OK) |

## Railway hub — inventory + maturity march

**Project:** `gleaming-cooperation` / `production`.  
**Skill:** [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md)

| Role | Service | Private / public |
|------|---------|------------------|
| central | `openfdd-central-cQ-F` | `openfdd-central-cq-f.railway.internal:8080` |
| mqtt | `openfdd-mqtt` | private 8883 (+ TCP proxy when approved) |
| web | `openfdd-web` | `https://openfdd-web-production-af99.up.railway.app` |

### Snapshot (pre-3.3.9 Publish, baseline `sha-9667888`)

| Service | Status | Notes |
|---------|--------|-------|
| central | Online | MQTT ingest off |
| web | Online | SPA OK; `/api` **404** |
| mqtt | **Crashed** | missing CA; no volumes |
| bosspi fieldbus | Up healthy | `sha-9667888` arm64; still aimed at prior broker |

### Maturity ladder

| Level | Gate | Status |
|------:|------|--------|
| L0 | tip `sha-*` on hub + Pi | Partial (mqtt crash; awaiting 3.3.9) |
| L1 | public `/api/health` 200 | **Blocked** → 3.3.9 |
| L2 | JWT + CSV | Optional backup |
| L3 | mqtt Online + ingest | **Blocked** (certs) |
| L4 | bosspi → Railway telemetry | Not started |
| Stream | ingest + no crash loops | Not started |
| L5 | FDD zn_t/duct_t | Not started |

**March:** L1 → L3 → L4 → stream → L5. No bench dual-MQTT cloud gate.

## Open findings (deferred — unfinished prior work)

| ID | Finding | Pointer |
|----|---------|---------|
| **H10** | Historian scale quals | [`HISTORIAN_PROGRAM.md`](../../openfdd_agent_spec/HISTORIAN_PROGRAM.md) |
| **issue-763-ml** | Engineering bundle phases 2–8 | [#763](https://github.com/bbartling/open-fdd/issues/763) |
| **dependabot-thrift** | Sticky thrift Dependabot | [`thrift-advisory.md`](../security/thrift-advisory.md) |
| **lint-sweep** | Scoped lint hygiene only | [`RUST_LINT_HYGIENE.md`](../../openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md) |
| **bench-dual-mqtt** | Deferred as cloud gate | Historical PASS only |

## Hygiene

- Living queue: CLOSE/remove only with evidence; never drop unfinished deferred.
- Tiny rev → GHCR → GH tidy → re-pin → gates → sync this file → repeat until north star.
- No secrets; no local docker build on bensbench; bosspi arm64 `sha-*` only.
