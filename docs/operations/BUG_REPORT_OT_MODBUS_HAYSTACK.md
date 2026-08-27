# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-26  
**Platform:** `3.3.4` / `sha-71e1336` (`71e1336` merge #784 on master)  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR=/workspace/.cache/datafusion-spill`)  
**Remote edge:** bosspi (`CLOUD_SIM_PI_SSH` in bench env) — fieldbus only (dual-MQTT gate 10)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local` / `rusty-haystack/.../.env`.

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-71e1336` | **PASS** (gate `00`) | `71e1336d95c9` | `3.3.4+71e1336d95c9` |
| bosspi | fieldbus edge only | `openfdd-fieldbus:sha-71e1336` | n/a | **PASS** `71e1336d95c9` == bench | fieldbus healthy (qemu amd64) |

Artifacts: `reports/nightly-ot-bench_20260826T202049Z/digests.txt`, `image_revs.txt`, `pi_image_rev.txt` (gate 10).

Digest equality (gate `00`): central / fieldbus / mqtt / mcp `nightly` == `sha-71e1336` (see `digests.txt`).

## Confirmed PASS (`sha-71e1336` after #784)

| Gate | Result |
|------|--------|
| `00` GHCR pull + nightly↔sha | **GATE PASSED** |
| `01` stack health | **GATE PASSED** |
| `02` BACnet OT (5007 + BIP + poll) | **GATE PASSED** — 15 pass |
| `03` MQTTS + Feather persistence | **GATE PASSED** |
| `04` Modbus OT | **GATE PASSED** |
| `05` Haystack live (`HAYSTACK_EXPECT_LIVE=1`) | **GATE PASSED** |
| `07` cloud-sim (bosspi edge) | **22 pass / 1 fail** — see open #526 below |
| `10` dual-MQTT sign-off | **GATE PASSED** |
| Synthetic-59 target pairs | **PASS** — 59/59 (prior tip) |

## Haystack via fieldbus (B1 / B2) — CLOSED

| Check | Result |
|-------|--------|
| `GET /haystack/about` via fieldbus | **OK** |
| Live curVal through fieldbus | **OK** — gate `extract_cur_val` fixed (#783) |
| Allowlist (`/haystack/eval`) | **OK** — HTTP 404 |

## B3 — MS/TP routing (device 5007) — CLOSED

**Prior failure:** empty shipped `field_devices.toml` on bench (no 5007 seed) + I-Am overwrite edge case.

**Fix train (#784):** vendored `DeviceTable::upsert` preserves routing; Who-Is merges `field_devices.toml`; seed logging.

**Re-verify (`sha-71e1336` + bench overlay):** `02_bacnet_ot.sh` **GATE PASSED** — 15 pass / 0 fail (`source_network=2000`, read AI:1173, poll 3 points).

Bench requires: `cp scripts/nightly-ot-bench/field_devices.bench.example.toml config/fieldbus/field_devices.toml` + fieldbus recreate.

## MQTT / cell optimization — SHIPPED (#784)

| Item | Before | After (`sha-71e1336`) |
|------|--------|----------------------|
| Default poll | 60 s | **300 s** (floor **60 s** unless `OPENFDD_FIELDBUS_DEV_FAST_POLL=1`) |
| MQTT publish | tied to poll, 5 s floor | `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS` (default 300, min 60) |
| Payload | full snapshot every cycle | `OPENFDD_MQTT_DELTA=1`, `OPENFDD_MQTT_CELL_MODE=1` (slim tags, no display_name) |
| Health subset | all points | `OPENFDD_POLL_HEALTH_ONLY=1` (~30% cap) |

Docs: [`BACNET_OT_POLICY.md`](BACNET_OT_POLICY.md), [`deploy/mqtt/README.md`](../../deploy/mqtt/README.md).

**Gate 03 / ingest:** **GATE PASSED** on `sha-71e1336` (ingest counter growth).

**Gate 10 note:** with 300 s publish interval, dual-MQTT peek uses combined wildcard subscribe (`MQTT_SUB_WAIT_SECS≥330`).

## Dual-site MQTT (lab + bldg2) — gate 10 — PASS

| Check | lab / fieldbus-1 @ bensbench | bldg2 / pi-1 @ bosspi |
|-------|-------------------------------|------------------------|
| GHCR fieldbus rev matches bench | n/a | **PASS** `71e1336d95c9` |
| MQTTS telemetry | **PASS** numeric values | **PASS** numeric values |
| Central `/api/edges` | listed + telemetry | listed + telemetry |
| Weather city | Madison (Open-Meteo) | Chicago (Open-Meteo) |
| Stack left running | yes | yes |

Run: `RUN_CLOUD_SIM=1 DUAL_MQTT_WAIT_SECS=600 MQTT_SUB_WAIT_SECS=330 ./scripts/nightly-ot-bench/run_all.sh`

**bosspi bootstrap:** minimal repo at `CLOUD_SIM_PI_REPO` needs `docker/compose.edge.yml`, `config/fieldbus/{gateway.toml,objects.csv}`, git init for gate `07` gateway patch.

## Open findings

| ID | Finding | Status |
|----|---------|--------|
| #526 | Hosted device 600000 absent from broadcast Who-Is (Pi edge); unicast I-Am to ephemeral source still skipped | **OPEN** — Workbench discovery on Pi-hosted instance |
| arm64 | No arm64 GHCR fieldbus; bosspi runs amd64 under qemu | **OPEN** — documented |
| #526 client | Fieldbus Who-Is bind ephemeral misses broadcast I-Am | **OPEN** — client-side |

## Agent / docs hygiene

- [`companion-rusty-bacnet-mcp.md`](../mcp-agents/companion-rusty-bacnet-mcp.md) — read-only BACnet debug MCP (not production poll).
- `OPENFDD_AGENT_PASSWORD` optional on LAN bench; Railway requires it.

## Hygiene

- #783 merged → `fa14c05` (Haystack gate + BUG_REPORT refresh).
- #784 merged → `71e1336` (B3 routing, OT policy, MQTT cell mode, gate 10, companion MCP docs).
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
