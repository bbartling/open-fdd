# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-26  
**Platform:** `3.3.4` / `fa14c05` master + `1540225` train (`feat/nightly-b3-mqtt-policy` PR pending)  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`, `OPENFDD_DATAFUSION_SPILL_DIR=/workspace/.cache/datafusion-spill`)  
**Remote edge:** bosspi `192.168.204.12` — fieldbus only (dual-MQTT gate 10)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local` / `rusty-haystack/.../.env`.

## GHCR legitimacy (required sign-off)

| Host | Role | Image ref | nightly↔sha | OCI revision | `/health` version |
|------|------|-----------|-------------|--------------|-------------------|
| bensbench | central / fieldbus / mqtt / web | `ghcr.io/bbartling/openfdd-*:sha-*` | from gate `00` `digests.txt` | `image_revs.txt` | `/api/health` |
| bosspi | fieldbus edge only | same `sha-*` fieldbus | n/a | must == bench fieldbus | `:8081/health` |

Artifacts: `reports/nightly-ot-*/digests.txt`, `image_revs.txt`, `pi_image_rev.txt` (gate 10).

## Confirmed PASS (master `fa14c05` after #783)

| Gate | Result |
|------|--------|
| Stack health `/api/health` | **PASS** on prior `sha-8e7899e` — re-pull after merge |
| Synthetic-59 target pairs | **PASS** — 59/59 (prior tip) |
| Modbus `04` vs Pi Modbus TCP sim | **GATE PASSED** |
| Haystack `05` live (`HAYSTACK_EXPECT_LIVE=1`) | **GATE PASSED** — B1/B2 closed; gate script stdin fix in #783 |
| Fieldbus `/health` | **PASS** — sidecars green |

## Haystack via fieldbus (B1 / B2) — CLOSED

| Check | Result |
|-------|--------|
| `GET /haystack/about` via fieldbus | **OK** |
| Live curVal through fieldbus | **OK** — gate `extract_cur_val` fixed (#783) |
| Allowlist (`/haystack/eval`) | **OK** — HTTP 404 |

## B3 — MS/TP routing (device 5007) — FIX IN PR TRAIN

**Symptom (prior tip):** Who-Is found 5007 but `source_network` null; ReadProperty UNKNOWN_OBJECT.

**Root cause:** I-Am responses without NPDU routing overwrote `add_routed_device` seeds in the ephemeral client device table.

**Fix (`1540225`):**

- Vendored `DeviceTable::upsert` preserves `source_network` / `source_address` when I-Am lacks routing.
- Who-Is merges configured routed devices from `field_devices.toml`.
- Structured log on successful `add_routed_device` seed.

**Re-verify:** `./scripts/nightly-ot-bench/02_bacnet_ot.sh` after GHCR pull of PR tip. Bench must mount [`field_devices.bench.example.toml`](../scripts/nightly-ot-bench/field_devices.bench.example.toml) → `config/fieldbus/field_devices.toml`.

## MQTT / cell optimization — NEW IN PR TRAIN

| Item | Before | After (`1540225`) |
|------|--------|-------------------|
| Default poll | 60 s | **300 s** (floor **60 s** unless `OPENFDD_FIELDBUS_DEV_FAST_POLL=1`) |
| MQTT publish | tied to poll, 5 s floor | `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS` (default 300, min 60) |
| Payload | full snapshot every cycle | `OPENFDD_MQTT_DELTA=1`, `OPENFDD_MQTT_CELL_MODE=1` (slim tags, no display_name) |
| Health subset | all points | `OPENFDD_POLL_HEALTH_ONLY=1` (~30% cap) |

Docs: [`BACNET_OT_POLICY.md`](BACNET_OT_POLICY.md), [`deploy/mqtt/README.md`](../../deploy/mqtt/README.md).

**Gate 03 / ingest:** Re-run after B3 + new fieldbus image; weather/hosted points may prove MQTT path even when OT BACnet poll is sparse.

## Dual-site MQTT (lab + bldg2) — gate 10

| Check | lab / fieldbus-1 @ bensbench | bldg2 / pi-1 @ bosspi |
|-------|-------------------------------|------------------------|
| GHCR fieldbus rev matches bench | n/a | **required PASS** |
| MQTTS telemetry | topic + numeric values | topic + numeric values |
| Central `/api/edges` | listed + telemetry | listed + telemetry |
| Weather city | Madison (Open-Meteo) | Chicago (Open-Meteo) |
| Stack left running | yes | yes |

Run: `RUN_CLOUD_SIM=1 DUAL_MQTT_WAIT_SECS=600 WEATHER_SOAK_SECS=600 ./scripts/nightly-ot-bench/run_all.sh`

## Agent / docs hygiene

- [`companion-rusty-bacnet-mcp.md`](../mcp-agents/companion-rusty-bacnet-mcp.md) — read-only BACnet debug MCP (not production poll).
- `OPENFDD_AGENT_PASSWORD` optional on LAN bench; Railway requires it.

## Hygiene

- #783 merged → master `fa14c05` (Haystack gate + BUG_REPORT refresh).
- #780 on `8e7899e`: edge kits, agent auth, nginx resolver executable.
- Do not local `docker build` stack on bensbench — GHCR `sha-*` only.
