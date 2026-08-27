# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-27  
**Platform:** `3.3.4` / `sha-6c2b89e` (merge #787 Who-Is INADDR_ANY; #786 discovery port bind)  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-6c2b89e` | pin tip explicitly if nightly lag | `6c2b89ee1fd1` | `3.3.4+6c2b89ee1fd1` |
| bosspi | fieldbus edge only | `openfdd-fieldbus:nightly` @ tip rev | n/a | **PASS** `6c2b89ee1fd1` == bench | fieldbus healthy (amd64/qemu until Plan 3) |

Prefer `OPENFDD_IMAGE_TAG=sha-6c2b89e` (or later tip) — do not trust sticky `:nightly` without digest check.

## Confirmed PASS (`sha-6c2b89e`)

| Gate / check | Result |
|------|--------|
| Who-Is F3 (#526 client) | **PASS** — `POST /bacnet/whois` lists **599999** + **600000** |
| Prior OT train (`sha-71e1336`) | Gates `00`–`05`, `10` dual-MQTT **PASS** (retained); gate `03` now Parquet persist |
| Synthetic-59 | **PASS** — 59/59 (prior tip) |

## #526 Who-Is client — CLOSED

**Root cause:** discovery socket used ephemeral port and/or unicast `OPENFDD_FIELDBUS_BIND` address → missed directed-broadcast I-Am on Linux.

**Fix:** `#786` bind discovery to `bacnet_server.port` with `SO_REUSEADDR`; `#787` bind Who-Is on **`0.0.0.0`** (not BIND unicast). Unicast reads stay ephemeral.

**Evidence (`sha-6c2b89e`):** devices include `600000` @ Pi BIP and `599999` (live or hosted_local fallback).

Unicast I-Am to ephemeral requester may still skip (server broadcasts I-Am) — Workbench on `:47808` is fine.

## Haystack / B3 / MQTT cell — CLOSED (prior)

See history on `sha-71e1336` (#783/#784): Haystack curVal, MS/TP 5007, 300 s poll / cell MQTT.

## Dual-site MQTT (lab + bldg2)

| Check | lab / fieldbus-1 | bldg2 / pi-1 |
|-------|------------------|--------------|
| Fieldbus rev tip | `6c2b89e` | `6c2b89e` |
| Who-Is sees peer hosted | 600000 from bench | n/a |
| MQTTS / `/api/edges` | recreate may need 300 s publish soak | restart edge after central recreate |

## Historian ledger (H)

| Item | Status |
|------|--------|
| H1–H9 Parquet path | **done** — canonical under `OPENFDD_STORAGE_URL` |
| Feather / dual-write / H6 migrate product | **Plan 4** — delete (no live sites to migrate) |
| Durable restore | same volume / `s3://` across GHCR image updates — **not** wipe `/workspace` |
| H10 TB quals | **OPEN** |
| Railway AI vs FDD AI | Railway may bootstrap GHCR; HVAC/FDD AI = local + **agent JWT** to private central |

## Open findings

| ID | Finding | Status |
|----|---------|--------|
| arm64 | No arm64 GHCR fieldbus; bosspi runs amd64 under qemu | **OPEN** — Plan 3 |
| H10 | Large historian quals | **OPEN** |
| nightly lag | `:nightly` may lag `sha-*` after multi-image publish | pin `sha-*` on benches |

## Hygiene

- #786 / #787 Who-Is client — tip `6c2b89e`.
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
- Anti-hardcoding: no private OT IPs in this report.
