---
title: Desktop app
parent: How-to Guides
nav_order: 11
description: "Open-FDD gateway, MCP RAG, React UI, Feather storage, and local ingest (start-local)."
---

# Open-FDD Desktop App

> **Retired in 2.4:** The monolithic gateway, MCP, and React UI were removed from this repository. New work uses **[Skills and agent shell](skills_and_agent)** and generated code under **`workspace/`**. The content below is historical reference.

## Goal

Run Open-FDD locally with a Python **HTTP gateway** (FastAPI, package `open_fdd.gateway`; colloquially the “bridge”) + MCP + web UI. The built-in AI path is **Codex CLI on the bridge host** via `/ai-agent` and `/openfdd-agent/chat`.

This repository includes a React UI workspace at `apps/desktop-ui` that talks to the gateway on port **8765** by default.
The recommended automation path is web-first (gateway + MCP + React UI) on the machine where Open-FDD runs.

The **built-in AI agent** (Codex) is instructed to write **new** code only under **`toolshed/scratch/`** in the workdir; see **[Toolshed](toolshed)** for layout and promotion to **`toolshed/published/`**.

## Install

```bash
pip install "open-fdd[desktop]"
```

## Launch

### Recommended: `start-local` (repo-local data under `stack/local-data`)

From the repository root, **`scripts/start-local.ps1`** (Windows) and **`scripts/start-local.sh`** (bash) export **`OFDD_DESKTOP_DATA_DIR`**, **`OFDD_MODEL_TTL_PATH`**, **`OFDD_MODEL_TTL_MIRROR_PATH`**, **`OFDD_TTL_SYNC_INTERVAL_SECONDS`**, and **`OFDD_BRIDGE_URL`** so **`model.json`**, Feather chunks, and **`data_model.ttl`** live under **`stack/local-data/`** (gitignored) instead of per-user app data.

Both scripts **rebuild `stack/mcp-rag/index/rag_index.json`** from **`docs/`** before starting **`open-fdd-mcp-rag`** (roles **`all`** and **`mcp`**), so MCP search matches current docs on each launch. Set **`OFDD_SKIP_MCP_INDEX_BUILD=1`** to skip that step when iterating quickly.

Windows — gateway, MCP RAG, and Vite dev UI each in a new PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -LanHost 192.168.1.10   # LAN dashboard (see Trusted private LAN)
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ListenAll   # bind 0.0.0.0 without picking a LAN IP (set OFDD_BRIDGE_URL or AI Agent Bridge base URL)
```

Single role in the current shell (`gateway` \| `mcp` \| `ui` \| `adapter`):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -Role gateway
```

Optional parameters: **`-BridgeUrl`**, **`-SyncIntervalSeconds`**, **`-LanHost <ipv4>`** (private LAN dashboard: binds gateway and MCP on **`0.0.0.0`**, runs Vite with **`--host 0.0.0.0`**, sets **`OFDD_CORS_ALLOW_PRIVATE_LAN=1`**, and points **`OFDD_BRIDGE_URL`**, **`OFDD_MCP_REST_BASE`**, and **`OFDD_UI_PUBLIC_BASE`** at `http://<ip>:8765` / `:8090` / `:5173`; open inbound **8765**, **8090**, **5173** on the host firewall if other PCs connect), and **`-ListenAll`** (same bind + Vite **`--host 0.0.0.0`** and private-LAN CORS default, but leaves public URL env vars unchanged unless you set them yourself).

Bash (macOS / Linux / WSL) — **`all`** runs gateway + MCP + UI in the background with logs under **`stack/local-data/logs/`**. The script writes **`stack/local-data/openfdd-agent-bootstrap.json`** and exports **`OFDD_AGENT_BOOTSTRAP_FILE`** (same behavior as **`start-local.ps1`**) so the **AI Agent** tab / **`GET /openfdd-agent/context`** see **`bridge_base`**, **`mcp_rest_base`**, and **`ui_public_base`**.

```bash
bash ./scripts/start-local.sh
bash ./scripts/start-local.sh gateway   # foreground gateway only
bash ./scripts/start-local.sh --lan-host 192.168.1.10 all   # same LAN defaults as -LanHost on Windows
bash ./scripts/start-local.sh --listen-all all              # bind 0.0.0.0 without --lan-host (set OFDD_BRIDGE_URL or AI Agent Bridge base URL)
# or: OFDD_LAN_HOST=192.168.1.10 bash ./scripts/start-local.sh
```

Override the bridge URL the same way on all platforms: **`export OFDD_BRIDGE_URL=http://127.0.0.1:9999`** before running the script (optional).

### Restarting `start-local` and MCP (important)
{: #restarting-start-local-and-mcp-important}

**MCP RAG** (`open-fdd-mcp-rag`, default **`127.0.0.1:8090`**) is designed like a normal server process: it reads **`OFDD_AGENT_BOOTSTRAP_FILE`**, **`OFDD_MCP_*`**, and the on-disk **`rag_index.json`** when it **starts**. It does **not** watch those files for live edits while running—the **`start-local`** scripts regenerate **`rag_index.json`** from **`docs/`** before launching MCP (unless **`OFDD_SKIP_MCP_INDEX_BUILD=1`**), then **`open-fdd-mcp-rag`** loads that snapshot until you stop and start it again.

| Situation | What to do |
|-----------|------------|
| You ran **`start-local`** again while old windows/PIDs are still up | **Windows:** close the previous **gateway**, **mcp-rag**, and **desktop-ui** PowerShell windows (or you risk **port conflicts** on **8765 / 8090 / 5173** and two different MCP instances). **macOS/Linux:** stop the old **`open-fdd-gateway`**, **`open-fdd-mcp-rag`**, and **`npm run dev`** jobs (see **`stack/local-data/logs/*.log`** for PIDs) before starting new ones. |
| You rebuilt the doc index (`python scripts/build_mcp_rag_index.py …`) | **Restart `open-fdd-mcp-rag`** so `GET /manifest` and `search_docs` see the new **`rag_index.json`**. |
| You changed bridge URL, MCP port, or bootstrap JSON | Restart **gateway and MCP** (and usually the UI) so every process agrees on the same env + **`openfdd-agent-bootstrap.json`**. |

So: **each clean `start-local` run should mean one trio of processes** (gateway + MCP + UI). Treat “refresh MCP” as **stop the old `mcp-rag` → start again** (the launcher does the start; you own the stop when re-launching).

**Codex on macOS:** install with **`npm install -g @openai/codex`**, then **`codex login`**. If the bridge cannot find the binary, set **`OFDD_CODEX_CMD`** to the full path (often under **`$(npm config get prefix)/bin/codex`**).

First-time UI: **`cd apps/desktop-ui && npm install`** once; the launcher runs **`npm run dev`** for the UI role.

After startup you should have:

- Gateway (same CLI as **`open-fdd-desktop-bridge`**): **`open_fdd.gateway`** — Swagger **`http://127.0.0.1:8765/docs`**, OpenAPI **`http://127.0.0.1:8765/openapi.json`**
- MCP RAG: **`http://127.0.0.1:8090`**
- Web UI: Vite default (typically **`http://127.0.0.1:5173`**); align **`OFDD_BRIDGE_URL`** / UI env with your bridge if you change ports.

**Readiness deep links:** `GET /assistant/readiness` builds UI URLs using **`OFDD_UI_PUBLIC_BASE`** (preferred) or **`OFDD_UI_PORT`** (defaults to **8080** in code if unset). With **`start-local`**, set **`OFDD_UI_PUBLIC_BASE=http://127.0.0.1:5173`** (the Windows script does this) so plot/data-model links match the Vite dev server.

### Built-in AI Agent (`/ai-agent`)

The **AI Agent** tab is the **built-in** Open-FDD AI surface: the bridge runs the **`codex` CLI** on the host today (same auth model as `codex login` / `codex login --device-auth`). The UI route **`/ai-agent`** replaces the older **`/openfdd-claw-chat`** path (which redirects for bookmarks). Endpoints:

- `GET /local-codex/diagnostics` — `codex login status`, `where` / npm hints (especially Windows), plus **`exec_env`** (how `codex exec` is invoked)
- `POST /local-codex/chat` — `codex exec …` for a simple transcript in the UI

#### Where Codex runs
{: #where-codex-runs}

| Layer | What it does |
|-------|----------------|
| **Desktop UI** (`apps/desktop-ui`, Vite / npm) | The browser talks to the bridge over HTTP (`/openfdd-agent/chat`, `/local-codex/*`, etc.). The UI **does not** execute Codex or Python rules locally—it only sends messages and shows replies. |
| **Open-FDD bridge** (**Python**, `open_fdd.gateway`) | The FastAPI gateway **orchestrates** each turn: it resolves the workdir, builds stdin/context, and **`subprocess.run`s** the **`codex` executable** on the **same host** as the bridge. Code lives in **`open_fdd/gateway/local_codex_cli.py`** and **`open_fdd/gateway/openfdd_agent.py`**. |
| **`codex` CLI** (OpenAI product) | Usually **installed with npm** (`npm install -g @openai/codex`), but at runtime it is a **normal OS child process** (e.g. `codex` / `codex.cmd`), not a long-lived “npm server.” **Subscriptions, OAuth/session, model choice, tool execution, and sandbox/approval behavior** for that process are **owned by Codex**; the bridge supplies **argv and env** (e.g. `OFDD_CODEX_EXEC_APPROVAL`, `OFDD_CODEX_EXEC_SANDBOX`, model overrides) so non-interactive runs can reach **localhost** and edit the configured repo path. |

So: **Python starts Codex; Codex runs the agent turn** under the flags and login you have on that machine. Tightening behavior is done with **Open-FDD env vars** (what we pass into `codex exec`) and/or **Codex’s own config and `codex login`**, not by moving execution into the Vite dev server.

**Codex exec sandbox (bridge host):** the bridge runs `codex --ask-for-approval … exec …` so the agent can call **localhost** (e.g. `http://127.0.0.1:8765`) and edit the workdir. Defaults: **`OFDD_CODEX_EXEC_APPROVAL=never`**, **`OFDD_CODEX_EXEC_SANDBOX=danger-full-access`**. Stricter options: `read-only`, `workspace-write` (with **`OFDD_CODEX_WORKSPACE_WRITE_NETWORK=true`** the bridge adds `-c sandbox_workspace_write.network_access=true`). Full bypass (only on locked-down automation hosts): **`OFDD_CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=1`**. See upstream [Codex sandbox](https://developers.openai.com/codex/concepts/sandboxing).

**Built-in agent model routing (`POST /openfdd-agent/chat` only):** SIMPLE tier uses **`--model gpt-5.4-mini`** (override **`OFDD_CODEX_MODEL_SIMPLE`**). COMPLEX uses **`gpt-5.5`** then retries once with **`gpt-5.4`** if stderr looks like an unknown-model error (override **`OFDD_CODEX_MODEL_COMPLEX`** / **`OFDD_CODEX_MODEL_COMPLEX_FALLBACK`**). By default, every **successful SIMPLE** turn runs a **second `codex exec`** using the **COMPLEX primary model** as a final critic/reviewer (disable with **`OFDD_AGENT_SIMPLE_COMPLEX_CRITIC=0`**; timeout **`OFDD_CODEX_EXEC_TIMEOUT_CRITIC`**). Optional: **`OFDD_CODEX_LLM_CLASSIFY=1`** runs another short **`codex exec`** with the simple model to choose SIMPLE vs COMPLEX before the main turn (extra latency/cost); **`OFDD_CODEX_CLASSIFY_TIMEOUT_S`** caps that call (default 120s). The UI **Send ▾** menu can send any message as **human-requested COMPLEX** (strong model regardless of auto-route).

**Agent chat thread context:** the UI sends the last **120** prior turns plus the new message. The bridge formats them into Codex stdin. History size is **`min(OFDD_AGENT_CHAT_HISTORY_MAX_TOKENS × 4 chars, OFDD_AGENT_CHAT_HISTORY_MAX_CHARS)`** using a rough **~4 characters per token** heuristic (`open_fdd/gateway/local_codex_cli.py`): defaults **`OFDD_AGENT_CHAT_HISTORY_MAX_TOKENS=8000`** (≈32k UTF‑8 bytes for prior turns) and **`OFDD_AGENT_CHAT_HISTORY_MAX_CHARS=120000`** as a hard ceiling. When over budget, **older turns are dropped** and a short “Earlier messages omitted…” line is prepended. **Rolling summarization** (a SIMPLE model compressing old turns + a verbatim tail) is optional product work; Open-FDD does not do it today.

The **AI Agent** tab uses a bridge device-code flow for Codex login status recovery. On completion the bridge writes **`$CODEX_HOME/auth.json`** (default **`~/.codex/auth.json`**) for ChatGPT-managed auth so **`codex exec`** on that host is signed in. OAuth tokens are **not** returned to the browser.

### Manual start (no launcher)

If you run **`open-fdd-desktop-bridge`** / **`open-fdd-gateway`** without **`start-local`**, writable storage defaults to the per-user **`open-fdd-desktop`** directory (see **Data model + BRICK**). Set **`OFDD_DESKTOP_DATA_DIR`** (and optionally **`OFDD_MODEL_TTL_PATH`**) yourself if you want a custom root.

```bash
# terminal 1
open-fdd-desktop-bridge

# terminal 2
open-fdd-mcp-rag

# terminal 3 — after npm install in apps/desktop-ui
cd apps/desktop-ui
npm run dev
```

Production-style static UI (build + static server) is optional; see **`apps/desktop-ui`** README for **`npm run build`** and static hosting.

Bridge URL consistency:

- **`start-local`** sets **`OFDD_BRIDGE_URL`** for child processes; match the UI’s bridge base URL (e.g. **`VITE_DESKTOP_BRIDGE_BASE`** at build time) to the same host/port.
- In the **AI Agent** tab, **Bridge base URL** (stored in the browser as `ofdd-bridge-base-override`) overrides **`VITE_DESKTOP_BRIDGE_BASE`** without rebuilding—useful when the UI is opened from another host or over an SSH tunnel.
- The gateway also honors **`OFDD_BRIDGE_HOST`** / **`OFDD_BRIDGE_PORT`** if you prefer host/port env vars instead of a full URL.

### Trusted private LAN (other PCs on the same network)

The stack defaults to **loopback** (`127.0.0.1`) so random machines cannot reach your bridge. For a **locked-down office / VLAN** where other workstations should use the UI and API, you intentionally **listen on all interfaces** and point URLs at the **bridge host’s LAN IP** (not for the public internet).

**One-shot launcher (recommended):** **`powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -LanHost 192.168.1.10`** or **`bash ./scripts/start-local.sh --lan-host 192.168.1.10 all`** applies the listen addresses, CORS flag, Vite bind, and public URL env vars described below. If you only need **listen on all interfaces** without rewriting URLs, use **`-ListenAll`** or **`bash ./scripts/start-local.sh --listen-all all`**, then set **`OFDD_BRIDGE_URL`** (and related bases) yourself or use the **AI Agent → Bridge base URL** field in the browser. Ensure **`apps/desktop-ui/.env.local`** (if present) does not force **`VITE_DESKTOP_BRIDGE_BASE`** back to localhost when LAN browsers must call the bridge.

Manual steps (equivalent to **`-LanHost` / `--lan-host`**):

1. **Gateway listen address** — bind `uvicorn` to all interfaces, then clients use your LAN IP:
   - `export OFDD_BRIDGE_HOST=0.0.0.0`
   - `export OFDD_BRIDGE_PORT=8765` *(optional if default)*
   - Browsers and tools call **`http://<bridge-lan-ip>:8765`** (example `http://192.168.1.10:8765`).
2. **MCP RAG** — same idea if other hosts must call MCP directly (Codex on the bridge often still uses `127.0.0.1`):
   - `export OFDD_MCP_LISTEN_HOST=0.0.0.0`
   - `export OFDD_MCP_LISTEN_PORT=8090` *(default)*  
3. **Vite dev server** — so other PCs can load the UI:
   - `cd apps/desktop-ui && npm run dev -- --host 0.0.0.0`
4. **Where the UI sends API traffic** — set **`apps/desktop-ui/.env.local`** (or build env) so the browser uses the bridge’s LAN address, not localhost:
   - `VITE_DESKTOP_BRIDGE_BASE=http://192.168.1.10:8765`
   - Or use **AI Agent → Bridge base URL** in the running UI (no rebuild).
5. **Bootstrap / readiness links** — for **`GET /openfdd-agent/context`**, **`OFDD_AGENT_BOOTSTRAP_FILE`**, and **`OFDD_UI_PUBLIC_BASE`**, use URLs that are valid **from the bridge host and from browsers on the LAN** (often `http://<bridge-ip>:8765`, `http://<bridge-ip>:8090`, `http://<ui-host-ip>:5173` or a shared hostname if you use DNS).
6. **CORS** — the bridge only allows localhost origins unless you opt in:
   - **`OFDD_CORS_ALLOW_PRIVATE_LAN=1`** — allow browser `Origin` matching common **RFC1918** IPv4 patterns (10/8, 192.168/16, 172.16–31) plus localhost, **or**
   - **`OFDD_CORS_EXTRA_ORIGINS=http://192.168.1.20:5173`** — comma-separated exact UI origins if you prefer an allowlist.
7. **OS firewall** — open inbound **8765**, **8090**, **5173** (or your ports) on the **private** profile only.

This does **not** add authentication or TLS; treat the bridge like an internal tool on a network you trust.

### Gateway HTTP API (Swagger / OpenAPI)

Once the gateway is running locally:

- Swagger UI: `http://127.0.0.1:8765/docs`
- OpenAPI JSON: `http://127.0.0.1:8765/openapi.json`

Use Swagger for endpoint discovery, request body examples, and quick local API testing for Codex-assisted or manual workflows. The Python package lives at `open_fdd/gateway/`; `open_fdd/desktop_bridge/` is a thin compatibility shim for older imports.

## MCP RAG service (agents)

`open-fdd` includes an **MCP-style RAG HTTP service** (REST on **8090** by default): **`GET /manifest`**, **`POST /tools/search_docs`**, **`POST /tools/search_api_capabilities`**, and optional **action** tools that proxy the bridge. Agents and Codex discover it via **`mcp_rest_base`** in **`GET /openfdd-agent/context`** (from **`OFDD_AGENT_BOOTSTRAP_FILE`** when you use **`start-local`**).

Docs for operators and LLM retrieval are indexed under **`stack/mcp-rag/`**; the **agent operator playbook** (`agent_operator_playbook.md`) is written to match what `search_docs` returns. **Design:** HTTP-first, explicit env, no hot-reload of the JSON index—see **[Restarting `start-local` and MCP](#restarting-start-local-and-mcp-important)** above.

Build the local retrieval index:

```bash
python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json
```

Run MCP RAG locally:

```bash
open-fdd-mcp-rag
# serves on http://127.0.0.1:8090
```

After changing **`rag_index.json`**, restart this process (or full **`start-local`**) so clients see updated chunks.

Key env vars:
- `OFDD_MCP_LISTEN_HOST` / `OFDD_MCP_LISTEN_PORT` (defaults `127.0.0.1` / `8090`; bind address for `open-fdd-mcp-rag` and for `/health`’s `mcp_listen_hint`)
- `OFDD_MCP_OFDD_API_URL` (default `http://127.0.0.1:8765`)
- `OFDD_MCP_OFDD_API_KEY`
- `OFDD_MCP_ENABLE_ACTION_TOOLS=true` (required for write/config/ingest proxy tools)
- `OFDD_MCP_RAG_INDEX_PATH` (default `./stack/mcp-rag/index/rag_index.json`)

Docker image scaffold:
- `stack/Dockerfile.mcp_rag`

**Platform drivers:** ingest implementations live under `open_fdd/platform/drivers/` (BACnet DIY JSON-RPC, Open-Meteo, CSV). `open_fdd/desktop/drivers/` re-exports the same symbols for backward compatibility.

**Headless BACnet loop (cron-friendly):** after `pip install -e ".[desktop]"`, run `open-fdd-headless-bacnet once` or `loop` (see `python -m open_fdd.platform.drivers.headless_bacnet -h`). Modes: `local` uses `IngestService` on disk; `bridge` POSTs to the running gateway at `/ingest/bacnet`.

**AI-assisted driver setup:** `GET /config/drivers/export` returns a sanitized JSON bundle; `POST /config/drivers/validate` checks a proposed bundle without applying. MCP exposes read tools `drivers_export` and `drivers_validate` that proxy those routes.

## Data ingest quickstart (gateway HTTP API)

Base URL:

- `http://127.0.0.1:8765`

### 1) Create or list sites

```bash
curl http://127.0.0.1:8765/sites
curl -X POST http://127.0.0.1:8765/sites -H "Content-Type: application/json" -d "{\"name\":\"HQ\"}"
```

### 2) CSV ingest (file path or upload)

```bash
# direct path
curl -X POST http://127.0.0.1:8765/ingest/csv \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\",\"source\":\"csv\",\"csv_path\":\"C:/data/site.csv\"}"
```

```bash
# multipart upload
curl -X POST http://127.0.0.1:8765/ingest/csv/upload \
  -F "site_id=<site-id>" \
  -F "source=csv" \
  -F "file=@C:/data/site.csv"
```

### 3) Open-Meteo weather ingest

```bash
# set weather config once
curl -X POST http://127.0.0.1:8765/config/weather \
  -H "Content-Type: application/json" \
  -d "{\"latitude\":42.36,\"longitude\":-71.06,\"timezone\":\"America/New_York\",\"base_url\":\"https://archive-api.open-meteo.com/v1/archive\"}"

# ingest weather rows
curl -X POST http://127.0.0.1:8765/ingest/weather \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\",\"days_back\":7}"
```

### 4) Onboard bulk-to-CSV (standalone tool)

Onboard ingest was moved out of the bridge/UI into a standalone Tkinter tool:

```bash
python tools/onboard_bulk_download_gui.py
```

Use that GUI to export CSV from Onboard, then import the CSV in Open-FDD via `/csv-import` (or `POST /ingest/csv` / upload).

### 5) BACnet ingest (one-shot) and polling

**DIY BACnet server contract (JSON-RPC, model point fields):** `POST /ingest/bacnet` expects a server implementing `client_read_multiple` with `device_instance` + `requests[]` (`object_identifier`, `property_identifier`) and returning values in request order.

If co-running **easy-aso** on the same host for optimization experiments, use its supervisor on **`18090`** (for example `easy-aso-supervisor --port 18090`) so Open-FDD MCP RAG can keep default **`8090`**.

```bash
# one-shot pull
curl -X POST http://127.0.0.1:8765/ingest/bacnet \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\",\"server_url\":\"http://192.168.204.18:8080\",\"api_key\":\"<token>\"}"

# enable 5-minute poll loop
curl -X POST http://127.0.0.1:8765/config/bacnet \
  -H "Content-Type: application/json" \
  -d "{\"enabled\":true,\"interval_seconds\":300,\"site_id\":\"<site-id>\",\"server_url\":\"http://192.168.204.18:8080\",\"api_key\":\"<token>\"}"
```

### 6) Join sources for analysis/plots

```bash
curl -X POST http://127.0.0.1:8765/timeseries/query \
  -H "Content-Type: application/json" \
  -d "{\"site_id\":\"<site-id>\",\"sources\":[\"csv\",\"weather\",\"bacnet\"],\"join_on_timestamp\":true,\"join_how\":\"outer\",\"limit\":10000}"
```

## CSV timestamp parsing expectations

Desktop CSV ingest is strict enough to catch bad files but flexible on common field formats:

- Timestamp column auto-detection prefers `timestamp`, then other time/date-like headers.
- Known timezone abbreviations like `EDT`, `EST`, `CDT`, `PDT`, etc. are normalized to UTC offsets before parsing.
- Parsing uses UTC-normalized datetimes and drops rows with unparseable timestamps.
- A minimum valid timestamp ratio is enforced; files with mostly bad timestamps return a clear validation error instead of silently importing junk data.

Recommended CSV practice:

- Include a dedicated timestamp column (`timestamp` preferred).
- Use ISO 8601 when possible (example: `2026-03-18T21:00:00-04:00`).
- Avoid mixed timestamp formats inside one file.

If import fails, fix timestamp formatting and retry.

## Data model + BRICK

- **`model.json`** is the operational on-disk model (CRUD via gateway). Path: **`<desktop_data_dir>/model.json`**, where **`desktop_data_dir`** is **`OFDD_DESKTOP_DATA_DIR`** if set, otherwise a per-user directory **`open-fdd-desktop`** under the OS app-data root (`%APPDATA%` on Windows, `~/.local/share` on Linux, `~/Library/Application Support` on macOS) — see **`open_fdd.desktop.storage.paths.desktop_data_dir`**.
- Generated BRICK TTL defaults to **`<desktop_data_dir>/data_model.ttl`**, unless **`OFDD_MODEL_TTL_PATH`** is set (optional mirror: **`OFDD_MODEL_TTL_MIRROR_PATH`**; interval: **`OFDD_TTL_SYNC_INTERVAL_SECONDS`**).
- **`scripts/start-local.*`** points both model and TTL at **`stack/local-data/`** in the clone so development data stays with the repo.
- BRICK input mapping for rules resolves through **`open_fdd.desktop.services.BrickService`**.

## Feather-first ingestion

- CSV, weather, and BACnet drivers write pandas frames into timestamped Feather files under **`<desktop_data_dir>/feather_store`** (same **`desktop_data_dir`** as above — e.g. **`stack/local-data/feather_store`** when using **`start-local`**).
- Feather path layout is source/site scoped:
  - `<desktop_data_dir>/feather_store/<safe_source>/<safe_site_id>/<timestamp>_<nonce>.feather`
- Storage remains append/chunk-based (many files per site/source) for reliability and backfill workflows.
- The gateway can still present a site-level joined view for plotting (multi-source virtual merge by timestamp), so operators get a single logical trend frame without rewriting raw files.
- Time-series reads for rules concatenate all Feather files for a selected `(source, site_id)` pair.
- Point metadata supports external refs like:
  - `feather://<source>/<site_id>/<metric>`
- These refs are persisted in the model and emitted in TTL via `ofdd:externalReference`.

## Rule loop behavior

- `open_fdd.desktop.rules.run_rule_loop_batched` executes rules with memory-aware chunking.
- If data fits available memory target, full-frame evaluation is used.
- Otherwise, DataFrames are chunked and processed with equivalent rule semantics.
- Chunk size can be user-forced from desktop (`chunk_rows`) or auto-estimated from available memory.
- Batched outputs are concatenated back into one result frame so downstream fault summaries behave the same as single-pass runs.

## Typical desktop workflow (current)

1. Create/select a site in the desktop model tab.
2. Ingest data (CSV import or weather/BACnet fetch) into Feather-backed storage.
3. Confirm points and external references in model + generated BRICK TTL.
4. Run rules from a local YAML rules directory.
5. For large datasets, use batched rule execution (`chunk_rows` > 0, or leave auto-estimation on).
6. Review fault columns and summaries from the merged output frame.

## Development

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -U pip
pip install -e ".[dev,desktop]"
pytest
```

