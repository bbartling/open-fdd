# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-27  
**Platform:** `3.3.4` / `sha-fadf167` (multi-arch fieldbus) + Plan 4 merge `sha-21fc909` on master  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-*` tip | pin tip explicitly if nightly lag | tip OCI rev | tip |
| bosspi | fieldbus edge only | `openfdd-fieldbus:sha-fadf167` **linux/arm64** | n/a | **PASS** `fadf167ee984` native | fieldbus **healthy** (no qemu) |

Prefer `OPENFDD_IMAGE_TAG=sha-<7>` — do not trust sticky `:nightly` without digest check.

## Confirmed PASS

| Gate / check | Result |
|------|--------|
| Who-Is F3 (#526 client) | **PASS** — `POST /bacnet/whois` lists **599999** + **600000** (`sha-6c2b89e`+) |
| bosspi native arm64 | **PASS** — `Arch=arm64`, health OK, ~905 MiB fieldbus-only (`sha-fadf167`) |
| Prior OT train | Gates `00`–`05`, `10` dual-MQTT **PASS** (retained); gate `03` = Parquet persist |
| Plan 4 Feather retire | **MERGED** `#789` (`sha-21fc909`) — Parquet / `OPENFDD_STORAGE_URL` only |

## #526 Who-Is client — CLOSED

**Root cause:** discovery socket used ephemeral port and/or unicast `OPENFDD_FIELDBUS_BIND` address → missed directed-broadcast I-Am on Linux.

**Fix:** `#786` bind discovery to `bacnet_server.port` with `SO_REUSEADDR`; `#787` bind Who-Is on **`0.0.0.0`** (not BIND unicast).

## Haystack / B3 / MQTT cell — CLOSED (prior)

See history on `sha-71e1336` (#783/#784).

## Dual-site MQTT (lab + bldg2)

| Check | lab / fieldbus-1 | bldg2 / pi-1 |
|-------|------------------|--------------|
| Fieldbus platform | amd64 bench | **linux/arm64** native |
| Fieldbus tip | pin `sha-*` | `sha-fadf167` (or later multi-arch tip) |
| Who-Is sees peer hosted | 600000 from bench | n/a |

## Historian ledger (H)

| Item | Status |
|------|--------|
| H1–H9 Parquet path | **done** — canonical under `OPENFDD_STORAGE_URL` |
| Feather / dual-write / H6 migrate product | **CLOSED** — `#789` |
| Durable restore | same volume / `s3://` across GHCR image updates |
| H10 TB quals | **OPEN** |
| Railway AI vs FDD AI | Railway may bootstrap GHCR; HVAC/FDD AI = local + **agent JWT** to private central |

## Open findings

| ID | Finding | Status |
|----|---------|--------|
| arm64 | Multi-arch fieldbus + bosspi native verify | **CLOSED** — Plan 3 |
| H10 | Large historian quals | **OPEN** |
| nightly lag | `:nightly` may lag `sha-*` after multi-image publish | pin `sha-*` on benches |

## Hygiene

- #786 / #787 Who-Is; #788 BUG_REPORT + arm64 publish; #789 Feather retire; Plan 3 gate `07` prefers `linux/arm64`.
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
- Anti-hardcoding: no private OT IPs in this report.
