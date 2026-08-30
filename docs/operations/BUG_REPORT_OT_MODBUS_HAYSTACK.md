# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-29  
**Platform:** `3.3.9` / `sha-2dce59a` (`3.3.9+2dce59a60f80` on Railway hub); mqtt ACL durable fix in **`3.3.10` / `sha-c55a547`** (Publish in flight)  
**Host:** bensbench (ops / Railway CLI); low-RAM bench stack optional  
**Remote edge:** bosspi — fieldbus `ghcr.io/bbartling/openfdd-fieldbus:sha-2dce59a` (`linux/arm64`)  
**Artifacts:** public health + edges API on Railway; FDD run `act-48f9431e` (soft-empty)  
**Train:** [`patch_cycle_3.3.9_railway_web_api`](../../../.cursor/plans/patch_cycle_3.3.9_railway_web_api.plan.md)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)  
**On GitHub (master tip):** https://github.com/bbartling/open-fdd/blob/master/docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | `/health` or evidence |
|------|------|-----------|-------------|------------------------|
| Railway hub | central / web | `openfdd-*:sha-2dce59a` | Publish **3.3.9** green | `/api/health` → `3.3.9+2dce59a60f80` |
| Railway hub | mqtt | `openfdd-mqtt:sha-2dce59a` (→ `sha-c55a547` when Publish done) | 3.3.10 Publish in progress | broker Online; TLS clients connected |
| bosspi | fieldbus | `openfdd-fieldbus:sha-2dce59a` arm64 | match | MQTTS → `reseau.proxy.rlwy.net:44763` |

Prefer `OPENFDD_IMAGE_TAG=sha-<7>` — do not trust sticky `:nightly` without digest check.

## Confirmed PASS (this cycle — bosspi → Railway)

| Gate | Result | Evidence |
|------|--------|----------|
| **L1** public `/api` | **PASS** | `curl …/api/health` + `/api/auth/status` → **200**; version `3.3.9+2dce59a60f80` |
| **L3** mqtt + ingest | **PASS** | `openfdd-mqtt` Online; cert volume; central `OPENFDD_MQTT_ENABLED=1`; ingest connected |
| **L4** bosspi → Railway | **PASS** | Pi TLS client `edge:bldg2:pi-1` on broker; `/api/edges` → `pi-1` **`has_telemetry=true`** |
| **Stream** | **PASS** | `/api/health` `edges:1`, `ingest_ok` advancing (11→12 over 65s); hub containers Online |
| nginx `/api` fix (#799) | **PASS** | variable `proxy_pass` without `/api/` suffix |

## This cycle — CLOSED

| ID | Resolution |
|----|------------|
| **railway-web-api-double-path** | **CLOSED** — 3.3.9 nginx fix; public `/api/health` 200 |
| **railway-mqtt-certs** | **CLOSED** — volume `openfdd-mqtt-volume` @ `/mosquitto/certs`; broker Online |
| **bosspi-railway-mqtt** | **CLOSED** — Pi MQTTS via TCP proxy; central ingest; `has_telemetry=true` |
| **railway-stream-health** | **CLOSED** — ingest counters move; mqtt+central+web Online after ACL fix |

## This cycle — OPEN

| ID | Finding | Notes | Next |
|----|---------|-------|------|
| **railway-fdd-zn-duct** | L5 FDD on bldg2 stream | `/api/fdd/run` → parquet cache missing; `/api/fdd/roles` empty (no `role_map.json`) | Package ingest or role map on hub; re-run SV-RANGE/RATE/FLATLINE |
| **railway-mqtt-acl-startup** | 3.3.9 image uses `acl_file /mosquitto/config/acl`; `RAILWAY_RUN_COMMAND` cp not applied on deploy | Ops: `cp /mosquitto/certs/acl` + SIGHUP; **3.3.10** points ACL at certs volume (#800) | Re-pin mqtt to `sha-c55a547` when Publish green |
| **bosspi-bacnet-poll** | Pi poll device 599999 times out | Separate local OT; stream still ingests | OT LAN / device instance on bosspi |
| **bench-stack-down** | react-ot exited 137 | Non-blocking | Optional local restore |

## Confirmed PASS (historical — 3.3.8 bench soak)

| Gate / check | Result |
|------|--------|
| `combined_ot_synth_validate` | **PASS** |
| `07_cloud_sim` (Pi) | **PASS** |
| `10_dual_mqtt_signoff` | **PASS** (historical bench; **not** cloud gate) |
| `11_bacnet_pcap_fp_scan` | **PASS** |
| BUILDING_100 UI smoke | **PASS** |

## Prior cycle (3.3.8) — CLOSED

| ID | Resolution |
|----|------------|
| coderabbit-storage | **CLOSED** #797 |
| bench-field-devices | **CLOSED** #797 |
| railway-web-resolver | **CLOSED** #797 |

## Railway hub — inventory + maturity march

**Project:** `gleaming-cooperation` / `production`.  
**Skill:** [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md)

| Role | Service | Private / public |
|------|---------|------------------|
| central | `openfdd-central-cQ-F` | `openfdd-central-cq-f.railway.internal:8080` |
| mqtt | `openfdd-mqtt` | `openfdd-mqtt.railway.internal:8883`; TCP `reseau.proxy.rlwy.net:44763` |
| web | `openfdd-web` | `https://openfdd-web-production-af99.up.railway.app` |

### Snapshot (2026-08-30 UTC)

| Service | Image | Status | Notes |
|---------|-------|--------|-------|
| central | `sha-2dce59a` | Online | `OPENFDD_SITE_ID=bldg2`, `OPENFDD_EDGE_ID=pi-1`, MQTT ingest on |
| web | `sha-2dce59a` | Online | `/api/health` 200 |
| mqtt | `sha-2dce59a` | Online | certs volume; real ACL on `/mosquitto/certs/acl` |
| bosspi fieldbus | `sha-2dce59a` arm64 | Healthy | `OPENFDD_MQTT_HOST=reseau.proxy.rlwy.net:44763` |

**Central MQTT env (ops):** `OPENFDD_MQTT_ENABLED=1`, broker `openfdd-mqtt.railway.internal:8883`, PEMs under `/workspace/mqtt/`, **`OPENFDD_SITE_ID=bldg2`** (required — default `local` misses Pi topics).

### Maturity ladder

| Level | Gate | Status |
|------:|------|--------|
| L0 | tip `sha-*` on hub + Pi | **PASS** (`2dce59a`; mqtt → `c55a547` pending) |
| L1 | public `/api/health` 200 | **PASS** |
| L2 | JWT + CSV | Optional backup |
| L3 | mqtt Online + ingest | **PASS** |
| L4 | bosspi → Railway telemetry | **PASS** |
| Stream | ingest + no crash loops | **PASS** |
| L5 | FDD zn_t/duct_t | **OPEN** (role_map + parquet gap) |

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
