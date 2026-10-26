# Removals during Vibe19 port

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

Checkpoint commit **`4fe1dc99`** recorded the gutted Open-FDD tree before port.

## Removed (531 files)

- **`edge/`** — monolithic edge binary (auth, drivers, csv ingest, old DataFusion FDD)
- **`workspace/dashboard/`** — React/Vite dashboard (**historical**; production UI is React `frontend/web`, not Vite `:5173`)
- **Docker / compose / Caddy** — deployment stacks for old architecture
- **Legacy docs** — archive, agent prompts, web-app routes, driver guides tied to removed code

## Preserved

- **`docs/rules/cookbook/`** — expression rule cookbook (online docs)
- **`docs/modeling/`** — Haystack assignment docs
- **`LICENSE`**, **`.github/`**, **`tests/selenium/`**, **`os/`**

## Not re-added in this port

- BACnet/Modbus/Haystack live drivers
- JWT auth / FastAPI edge API
- MCP server
- Pandas production dashboard

These may return as separate layers on top of the Rust engine later.
