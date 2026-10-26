# Retired for Wave-NF 4.0

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

This file is a **legacy OT / ACME fieldbus tip**. Normal 4.0 does not publish or
start `openfdd-fieldbus`, and MCP does not advertise BACnet, Haystack wire, or
driver-discovery tools. Portal ingest is central + web + Timescale. Provider
tools `openfdd_provider_health` and `openfdd_provider_sites` stay. The OT archive
render (no containers) is:

```bash
OPENFDD_OT_ARCHIVE_RESTORE=1 ./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay
```

Do not re-pin or recreate fieldbus from the procedure below.

# Candidate tip (start) — Soft-OPEN suite (API / endpoint Soft-OPEN)

- **LIVE TIP:** VERSION **3.6.18** / GHCR **sha-6846568** / merge `68465681` (newest hub after #1287). Fieldbus publish may still finish — re-check `openfdd-fieldbus:sha-6846568` before ACME fieldbus recreate if missing.
- Plan: `.cursor/plans/post_wave_x_3619_softopen_ghcr_grok_enhance_20261017.plan.md`
- ART: `~/Documents/openfdd-softopen-art/3.6.18/` — **append new files, never overwrite**
- Soft-OPEN ≠ FQ. Timescale only. **No backups.** No volume deletes. No BACnet writes.
- **UI Soft-OPEN = JWT REST endpoints only** — prove data on the wire (`point_count` / series / JSON bodies) and **HTTP / error contracts**. **No screenshots. No headed browser Soft-OPEN. No Playwright/Selenium Soft-OPEN galleries.**

# Grok Soft-OPEN — ACME + Railway (authorized ops)

## FORBIDDEN

1. No site/DB/volume backups.  
2. No Desktop worktrees — `/tmp/openfdd-softopen/` only.  
3. No dual-write / Parquet / DataFusion / 3.5.x.  
4. No `compose down -v` / volume prune.  
5. No BACnet writes without human approval.  
6. Do not close GitHub issues — recommend CLOSE/KEEP/OPEN-NEW only.  
7. **No screenshot Soft-OPEN** — no PNG galleries, no SPA click Soft-OPEN. Endpoint JSON + status codes are enough.

## Part 0 — GHCR tip → Grok updates Railway + ACME

1. Work from **Linux `/tmp` tip checkout only** (no Desktop compiles).  
2. Pin **sha-6846568** (or newer-by-OCI-created if publish moved):  
   `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-mqtt openfdd-fieldbus`  
   Prefer the `sha-*` matching `3.6.18` / `6846568`.  
3. **Grok re-pins Railway hub** (central→mqtt→web) **and ACME** (fieldbus→hub MQTTS; Timescale only). **No backups.**  
4. `./scripts/ops/assert_hub_env_after_repin.sh sha-6846568` must PASS (proxy ≠ stale Soft-OPEN port).  
5. `edges≥1`; `ingest_ok` climbs across **≥2** publish cycles.  
6. `openfdd_fieldbus_railway_up.sh` must **not** tear down ACME hub (default).

## Part 0b — Missing data in Railway Timescale (FAIL-closed)

For each Soft-OPEN site (BUILDING_100 / SYNTH_* / unique Soft-OPEN id): every **package-mapped** role must have historian/point-resolve **sample count > 0**. Mapped-but-0 = Soft-OPEN **FAIL**. List gaps in ART; re-seed only with owner OK.

## Part 1 — Every open GitHub issue

Write `ISSUE_TRIAGE_<date>.md`. For **each** open issue: tip evidence → **CLOSE / KEEP / OPEN-NEW**. Include #1277–#1284, #1069, Haystack residuals, overlay draft. Owner decides closes. Report any **stale Soft-OPEN branches/PRs** still open after tip ship.

## Part 2 — Soft-OPEN suite (lessons + stress + DB + API plot/error bools)

From `/tmp` tip checkout against Railway web/central — **curl / Python JWT clients only**:

```bash
export OPENFDD_AGENT_PASSWORD=…   # never print
python scripts/softopen/run_softopen_railway.py \
  --base-url https://openfdd-web-production.up.railway.app \
  --building-id SYNTH_03 \
  --assert-hub --shortsha 6846568
```

Also:

```bash
python scripts/lessons/lesson_01_sites_and_equipment.py --base-url https://openfdd-web-production.up.railway.app --building-id SYNTH_03
python scripts/lessons/lesson_03_fc1_dataframe.py --base-url https://openfdd-web-production.up.railway.app --building-id SYNTH_03
# expect FC1 status ≠ SKIPPED_MISSING_ROLES
python scripts/lessons/lesson_05_rdf_semantic_meta_put.py --base-url https://openfdd-web-production.up.railway.app --building-id SYNTH_03
```

| Gate | Pass criterion |
| --- | --- |
| Lessons | 01 / 03 / 05 exit 0 (03: FC1 evaluates) |
| Stress | `run_gate.py --remote-api` — **pandas == SQL** fail-closed |
| DB | mapped roles → point-resolve `point_count > 0` (mapped-but-0 = FAIL) |
| Product/API Soft-OPEN | JWT GETs for health, AFDD, Overview analytics, FDD plot/series, RCx — **2xx + non-empty expected data**; **4xx/5xx / empty applicable = FAIL**. **No screenshots.** |
| Actions | `ACTIONS_TRIAGE_6846568.md` — green skip ≠ pass |

## Exit

Morning STATUS under `~/Documents/openfdd-softopen-art/3.6.18/`. Soft-OPEN ≠ FQ. **No screenshot ART.** ZAP not required this Soft-OPEN.
