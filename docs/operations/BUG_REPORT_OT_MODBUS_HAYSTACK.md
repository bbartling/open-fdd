# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-30 (3.3.11 closeout train)  
**Platform:** Railway hub **`3.3.9+2dce59a60f80`** (central/web `sha-2dce59a`); mqtt tip **`sha-5e58ee1`**; tip VERSION before bump **`3.3.10`** → train ships **`3.3.11`**  
**Host:** bensbench (ops / Railway CLI); low-RAM bench stack optional / down  
**Remote edge:** bosspi — fieldbus `ghcr.io/bbartling/openfdd-fieldbus:sha-2dce59a` (`linux/arm64`), **STOPPED** pending tip re-pin + 60s scrape lock  
**Train:** patch_cycle_3.3.11 closeout (P0 UI / MQTT≡CSV / tip pin)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)  
**On GitHub (master tip):** https://github.com/bbartling/open-fdd/blob/master/docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md

## Verdict — is bosspi streaming to Railway?

**Was YES** (ingest historically 700+). Fieldbus container **Exited** (operator stop). Re-enable only after tip pin + poll/publish **60s** floor.

| Check (2026-08-30) | Evidence |
|--------------------|----------|
| Public `/api/health` | `200` — `version=3.3.9+2dce59a60f80`, `edges:1`, `ingest_ok` **710** (stale while Pi stopped) |
| Hub containers | central + web + mqtt **Online** |
| SPA P0 | Overview blank; no MQTT charts; BUILDING_100 upload **401** + **`ERR_HTTP2_PROTOCOL_ERROR`** (nginx default 1m body vs central 128m) |
| Tip vs hub | tip `7163be98` / GHCR Publish green; hub **stale** on `sha-2dce59a` |

## GHCR legitimacy

| Host | Role | Image ref | Notes |
|------|------|-----------|-------|
| Railway central / web | hub | `openfdd-*:sha-2dce59a` | Sidebar `3.3.9+2dce59a` — **P0 stale pin** |
| Railway mqtt | broker | `openfdd-mqtt:sha-5e58ee1` | tip ACL path |
| bosspi | fieldbus | `openfdd-fieldbus:sha-2dce59a` arm64 | **Stopped**; publish was 60s |
| Tip Publish | stack | `sha-7163be9` available | Re-pin after 3.3.11 Publish |

## Confirmed PASS (prior 3.3.9 train — do not redo)

| Gate | Result |
|------|--------|
| **L1** public `/api` | **PASS** |
| **L3** mqtt + ingest | **PASS** |
| **L4** bosspi → Railway | **PASS** (when fieldbus up) |
| nginx `/api` double-path (#799) | **PASS** |
| mqtt durable ACL (#800) | **PASS** |

## This cycle — CLOSED (prior)

| ID | Resolution |
|----|------------|
| **railway-web-api-double-path** | **CLOSED** #799 |
| **railway-mqtt-certs** | **CLOSED** |
| **bosspi-railway-mqtt** | **CLOSED** |
| **railway-stream-health** | **CLOSED** |
| **railway-mqtt-acl-startup** | **CLOSED** |

## This cycle — OPEN P0 (3.3.11)

| ID | Finding | Next |
|----|---------|------|
| **railway-spa-overview-blank** | Overview blank — no plots / analytics | Tip re-pin + role normalize + historian |
| **railway-mqtt-no-charts** | Ingest ≠ charts (`zonetemp`/`sa_t` vs cookbook) | `normalize_role` aliases → `zone_t`/`sat` |
| **railway-csv-import-http2** | Package upload 401 + HTTP2 error | JWT + nginx `client_max_body_size 128m` |
| **railway-agent-stale-pin** | Hub on 3.3.9 while tip newer | Always re-pin after Publish |
| **bosspi-scrape-60s-only** | OT floor | publish=60 already; set poll=60; no DEV_FAST |
| **railway-fdd-zn-duct** | L5 empty roles / parquet | roles after alias + data |
| **telemetry-role-naming** | Live tags vs cookbook | product synonym in fdd_core |
| **railway-hub-image-skew** | central/web/Pi ≠ mqtt tip | re-pin all to 3.3.11 `sha-*` |
| **railway-central-patch-backup** | no Railway backup runbook | `scripts/railway_central_workspace_backup.sh` + docs |
| **bosspi-bacnet-poll-599999** | P1 — weather device timeouts | drop/skip device **599999**; outdoor air points bad/null |
| **ghcr-mqtt-sha-c55a547-missing** | P2 cosmetic | superseded by tip |

## Point sample (when streaming)

ZoneTemp (`role=zonetemp` → normalize `zone_t`), SA-T (`role=sa_t` → `sat`); outdoor air temp/humidity from device **599999** quality **bad**/null.

## Railway hub inventory

**Project:** `gleaming-cooperation` / `production`.  
**Skill:** [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md)

| Role | Service |
|------|---------|
| central | `openfdd-central-cQ-F` |
| mqtt | `openfdd-mqtt` (+ TCP `reseau.proxy.rlwy.net:44763`) |
| web | `https://openfdd-web-production-af99.up.railway.app` |

**Hard rules:** backup `/workspace` before central re-pin; never new empty volume; OT poll+publish **≥60s**.

## Deferred (out of 3.3.11)

| ID | Pointer |
|----|---------|
| **H10** | historian program |
| **issue-763-ml** | [#763](https://github.com/bbartling/open-fdd/issues/763) |
| **dependabot-thrift** | [#804](https://github.com/bbartling/open-fdd/issues/804) after lint-sweep |
| **lint-sweep** | [#803](https://github.com/bbartling/open-fdd/issues/803) first |
| **bench-dual-mqtt** | not cloud gate |
| **vibe13** | separate playground |

## Hygiene

- Living report: CLOSE only with evidence.
- Tiny rev → GHCR → GH tidy → **backup** → re-pin tip → gates → sync this file.
- No secrets; no local docker build on bensbench; bosspi arm64 `sha-*` only.
