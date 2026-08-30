# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-30 (3.3.11 closeout — tip pin + dual pipeline)  
**Platform:** Railway hub **`3.3.11+91fb3501aed2`** (central/mqtt/web `sha-91fb350`); local react stack same tip  
**Host:** bensbench (ops / Railway CLI / local GHCR pull); bosspi arm64 edge  
**Remote edge:** bosspi — fieldbus `ghcr.io/bbartling/openfdd-fieldbus:sha-91fb350`, poll+publish **60s**, site `bldg2` / edge `pi-1` → Railway MQTTS proxy  
**Local hub:** `OPENFDD_IMAGE_TAG=sha-91fb350` react recipe (mqtt+central+web); firewall/on-prem path  
**Train:** patch_cycle_3.3.11 closeout (dual Railway + local)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local`.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)  
**On GitHub (master tip):** https://github.com/bbartling/open-fdd/blob/master/docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md

## Verdict — bosspi → Railway

**YES** after tip re-pin (2026-08-30T20:11Z+).

| Check (2026-08-30 closeout) | Evidence |
|-----------------------------|----------|
| Public `/api/health` | `200` — `version=3.3.11+91fb3501aed2`, `edges:1`, `ingest_ok` advancing (10+) |
| Hub containers | central + web + mqtt **Online** on `sha-91fb350` |
| Workspace after re-pin | Intact — historian parquet under `/workspace/openfdd` (backup `~/openfdd-backups/railway/20260830T195849Z/`) |
| BUILDING_100 CSV | `POST /api/csv/import/package` **HTTP 200** |
| FDD registry | `POST /api/fdd/run` **ok** after `OPENFDD_PARQUET_ROOT=/workspace/openfdd` |
| bosspi OT | poll=60s publish=60s; weather **599999** disabled |

## Dual pipeline

| Pipeline | Edge | Hub | Status |
|----------|------|-----|--------|
| **A Cloud** | bosspi → `reseau.proxy.rlwy.net:44763` | Railway `sha-91fb350` | **PASS** streaming |
| **B Local** | (optional bench fieldbus → local mqtt) | bensbench react `sha-91fb350` | Hub **PASS**; B100 import **200**; FDD soft-OPEN (long runtime on full B100) |

## GHCR legitimacy

| Host | Role | Image ref | Notes |
|------|------|-----------|-------|
| Railway central/mqtt/web | hub | `openfdd-*:sha-91fb350` | `/api/health` `3.3.11+91fb350` |
| bosspi | fieldbus | `openfdd-fieldbus:sha-91fb350` arm64 | 60s floor |
| bensbench local | react stack | `openfdd-*:sha-91fb350` | pull only |
| Tip Publish | stack | [Publish green](https://github.com/bbartling/open-fdd/actions/runs/33320057823) | |

## Confirmed PASS

| Gate | Result |
|------|--------|
| **L1** public `/api` | **PASS** tip |
| **L3** mqtt + ingest | **PASS** |
| **L4** bosspi → Railway | **PASS** |
| CSV import BUILDING_100 (Railway + local) | **PASS** HTTP 200 |
| FDD run BUILDING_100 (Railway) | **PASS** with `OPENFDD_PARQUET_ROOT` |
| Backup before re-pin | **PASS** |
| Tip pin / no skew | **PASS** |
| nginx `/api` double-path (#799) | **PASS** (prior) |
| mqtt durable ACL (#800) | **PASS** (prior) |

## This cycle — CLOSED

| ID | Resolution |
|----|------------|
| **railway-agent-stale-pin** | **CLOSED** — hub `3.3.11+91fb350` |
| **railway-hub-image-skew** | **CLOSED** — central/mqtt/web/Pi same tip |
| **railway-csv-import-http2** | **CLOSED** — #806 body 128m + tip web; import 200 |
| **bosspi-scrape-60s-only** | **CLOSED** — poll+publish 60s on tip fieldbus |
| **railway-central-patch-backup** | **CLOSED** — script + backup `20260830T195849Z` before pin |
| **railway-fdd-zn-duct** / package FDD | **CLOSED** for CSV path — FDD ok on BUILDING_100; live MQTT roles soft-OPEN if Overview empty |
| **ghcr-mqtt-sha-c55a547-missing** | **CLOSED** superseded by tip |

## Soft-OPEN / follow-up

| ID | Notes |
|----|-------|
| **railway-spa-overview-blank** / **railway-mqtt-no-charts** | Stream + CSV data present; confirm SPA Overview/RCx plots in browser (API path validated). Live `role_map.json` still missing under workspace — MQTT charts may need ops role_map for bldg2 |
| **telemetry-role-naming** | Product aliases in tip (`zonetemp`→`zone_t`, `sa_t`→`sat`); still prefer hub role_map for full cookbook |
| **local-fdd-latency** | Full B100 `/api/fdd/run` can exceed 120–180s locally — use `OPENFDD_PARQUET_ROOT=/workspace/openfdd`; consider rule subset for smoke |
| **dual-pipeline-parity soak** | ≥1h soak both edges still recommended; cloud stream running |
| **bosspi-bacnet-poll-599999** | Device disabled in `field_devices.toml` |
| **Optional BACnet→MQTT CI** | Sticky optional workflow failure — not a product gate; deleted tip run where possible |

## Point sample (streaming)

ZoneTemp / SA-T from BIP benches on the OT LAN; outdoor weather device **599999** skipped.

## Railway hub inventory

**Project:** `gleaming-cooperation` / `production`.  
**Skill:** [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md)

| Role | Service |
|------|---------|
| central | `openfdd-central-cQ-F` |
| mqtt | `openfdd-mqtt` |
| web | `openfdd-web` → https://openfdd-web-production-af99.up.railway.app |

## Ops notes (this closeout)

1. Backup: `./scripts/railway_central_workspace_backup.sh` before every central re-pin.  
2. Re-pin order: central → mqtt → web; then bosspi fieldbus tip. Redeploy central after mqtt if ingest stuck at 0.  
3. FDD against historian packages: set **`OPENFDD_PARQUET_ROOT=/workspace/openfdd`** (Railway variable) when `OPENFDD_STORAGE_URL=file:///workspace/openfdd`.  
4. Tip mqtt image expects ACL at **`/mosquitto/certs/acl`** (local: place file under `deploy/mqtt/certs/acl`).  
5. Dual pipeline: bosspi→Railway only; local stack for firewall/on-prem — do not cross-wire for parity gate.  
