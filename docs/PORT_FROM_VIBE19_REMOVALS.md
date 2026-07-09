# Removals during Vibe19 port

Checkpoint commit **`4fe1dc99`** recorded the gutted Open-FDD tree before port.

## Removed (531 files)

- **`edge/`** — monolithic edge binary (auth, drivers, csv ingest, old DataFusion FDD)
- **`workspace/dashboard/`** — React/Vite dashboard (future production UI TBD)
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
- Streamlit / pandas production dashboard

These may return as separate layers on top of the Rust engine later.
