# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-30 (UTC refresh)  
**Platform:** Railway hub **`3.3.9+2dce59a60f80`** (central/web `sha-2dce59a`); mqtt tip **`sha-5e58ee1`** (includes #800 durable ACL + #801 docs Publish); VERSION tip **`3.3.10`**  
**Host:** bensbench (ops / Railway CLI); low-RAM bench stack optional / down  
**Remote edge:** bosspi — fieldbus `ghcr.io/bbartling/openfdd-fieldbus:sha-2dce59a` (`linux/arm64`), healthy 12h+  
**Train:** [`patch_cycle_3.3.9_railway_web_api`](../../../.cursor/plans/patch_cycle_3.3.9_railway_web_api.plan.md)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)  
**On GitHub (master tip):** https://github.com/bbartling/open-fdd/blob/master/docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md

## Verdict — is bosspi streaming to Railway?

**YES.** Live path `bosspi fieldbus → Railway MQTTS → central ingest → public web /api` is healthy.

| Check (2026-08-30 ~12:30Z) | Evidence |
|----------------------------|----------|
| Public `/api/health` | `200` — `edges:1`, `ingest_ok` **708→709** over ~70s (later **709+**; overnight climbed to **700+**) |
| `/api/edges` | `pi-1` / `bldg2` **`has_telemetry=true`** |
| `/api/mqtt/monitor` | connected; `received_messages` **710+**; `errors:0` `reconnects:0` |
| Recent telemetry | `openfdd/v1/sites/bldg2/edges/pi-1/telemetry/bacnet` ~every 60s |
| Point sample | **ZoneTemp** (`role=zonetemp`, good, 180.0), **SA-T** (`role=sa_t`, good, 180.0); **OA-T/OA-RH** from device **599999** quality **bad**/null |
| Hub containers | central + web + mqtt **Online** |
| Pi | fieldbus **healthy**, MQTT host `reseau.proxy.rlwy.net:44763` |

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | Notes |
|------|------|-----------|-------|
| Railway central / web | hub | `openfdd-*:sha-2dce59a` | `/api/health` → `3.3.9+2dce59a60f80` |
| Railway mqtt | broker | `openfdd-mqtt:sha-5e58ee1` | tip Publish after #801; loads ACL from `/mosquitto/certs/acl` |
| bosspi | fieldbus | `openfdd-fieldbus:sha-2dce59a` arm64 | MQTTS → Railway TCP proxy |
| GHCR note | — | `sha-c55a547` **mqtt tag missing** | #800 Publish was **cancelled**; durable ACL still in tip via `sha-5e58ee1` rebuild |

Prefer `OPENFDD_IMAGE_TAG=sha-<7>` — do not trust sticky `:nightly` without digest check.

## Confirmed PASS (this cycle — bosspi → Railway)

| Gate | Result | Evidence |
|------|--------|----------|
| **L1** public `/api` | **PASS** | `/api/health` + `/api/auth/status` **200** |
| **L3** mqtt + ingest | **PASS** | mqtt Online; cert volume; central `OPENFDD_MQTT_ENABLED=1`; ingest connected |
| **L4** bosspi → Railway | **PASS** | Pi TLS `edge:bldg2:pi-1`; `has_telemetry=true` |
| **Stream** | **PASS** | ingest advancing overnight (→700+); mqtt msgs ~1/min; hub Online |
| nginx `/api` fix (#799) | **PASS** | variable `proxy_pass` without `/api/` suffix |
| mqtt durable ACL (#800 content) | **PASS** | tip mqtt `sha-5e58ee1` loads `/mosquitto/certs/acl` (perms hardened `0700` mosquitto) |

## This cycle — CLOSED

| ID | Resolution |
|----|------------|
| **railway-web-api-double-path** | **CLOSED** — 3.3.9 nginx fix (#799) |
| **railway-mqtt-certs** | **CLOSED** — volume `openfdd-mqtt-volume` @ `/mosquitto/certs` |
| **bosspi-railway-mqtt** | **CLOSED** — Pi MQTTS via TCP proxy; central ingest |
| **railway-stream-health** | **CLOSED** — ingest counters move; hub Online |
| **railway-mqtt-acl-startup** | **CLOSED** — tip mqtt `sha-5e58ee1` uses certs-volume ACL; ops copy/`RAILWAY_RUN_COMMAND` no longer required |

## This cycle — OPEN

| ID | Finding | Notes | Next |
|----|---------|-------|------|
| **railway-fdd-zn-duct** | L5 FDD on bldg2 stream | `/api/fdd/run` → parquet cache missing; `/api/fdd/roles` empty (no hub `role_map.json`). Stream tags use `zonetemp` / `sa_t` (not cookbook `zn_t` / `duct_t`) | Add role_map / package ingest on Railway; map or alias roles; re-run SV-RANGE / RATE / FLATLINE |
| **bosspi-bacnet-poll-599999** | Pi poll **device 599999** times out every cycle | Local OT / weather object unreachable; OA-T/OA-RH publish as **bad**/null. Zone + SA still good → stream stays healthy | Fix OT path to hosted weather or drop 599999 from Pi poll config |
| **railway-hub-image-skew** | central/web still `sha-2dce59a` (3.3.9); mqtt on tip `sha-5e58ee1` | Intentional for now; optional full re-pin of central/web/fieldbus to tip | Re-pin when next product bump needs it |
| **ghcr-mqtt-sha-c55a547-missing** | Tag `openfdd-mqtt:sha-c55a547` never published | #800 Publish cancelled; superseded by tip rebuild | Cosmetic — use `sha-5e58ee1` or re-run Publish for historical tag |
| **bench-stack-down** | react-ot exited 137 | Non-blocking; not a cloud gate | Optional local restore |
| **telemetry-role-naming** | Live roles `zonetemp`/`sa_t` vs FDD cookbook `zn_t`/`duct_t` | Blocks clean L5 without alias/map | Align edge tags or hub role_map |

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

### Snapshot (2026-08-30 ~12:35Z)

| Service | Image | Status | Notes |
|---------|-------|--------|-------|
| central | `sha-2dce59a` | Online | `OPENFDD_SITE_ID=bldg2`, `OPENFDD_EDGE_ID=pi-1`, MQTT ingest on |
| web | `sha-2dce59a` | Online | `/api/health` 200 |
| mqtt | `sha-5e58ee1` | Online | ACL from `/mosquitto/certs/acl` |
| bosspi fieldbus | `sha-2dce59a` arm64 | Healthy | `OPENFDD_MQTT_HOST=reseau.proxy.rlwy.net:44763` |

**Central MQTT env (ops):** `OPENFDD_MQTT_ENABLED=1`, broker `openfdd-mqtt.railway.internal:8883`, PEMs under `/workspace/mqtt/`, **`OPENFDD_SITE_ID=bldg2`** (required — default `local` misses Pi topics).

### Maturity ladder

| Level | Gate | Status |
|------:|------|--------|
| L0 | tip `sha-*` on hub + Pi | **PASS** (mqtt tip; central/web/Pi on 3.3.9 pin — see skew OPEN) |
| L1 | public `/api/health` 200 | **PASS** |
| L2 | JWT + CSV | Optional backup |
| L3 | mqtt Online + ingest | **PASS** |
| L4 | bosspi → Railway telemetry | **PASS** |
| Stream | ingest + no crash loops | **PASS** (live) |
| L5 | FDD zn_t/duct_t | **OPEN** (parquet + role_map / role-name gap) |

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
