# OpenClaw + Open-FDD runbook

**Architecture we use:** run **Open-FDD on the host** (Windows: `scripts/start-local.ps1`; macOS/Linux/WSL: `scripts/start-local.sh`). Run **OpenClaw in Docker** only if you want; it acts as a **client** and reaches the bridge/MCP over HTTP to the **host OS** (e.g. `http://host.docker.internal:8765` from containers on Docker Desktop). **Do not** run Open-FDD inside the OpenClaw gateway container for this flow.

Single reference for **local Open-FDD setup**, **OpenClaw-as-client networking**, **first-time smoke**, **Phase 2** (git pull, dashboard flows, merged time-series, FDD), and **DIY BACnet** bridge scraping. Paste the **prompt** blocks into OpenClaw as needed.

**Contents**

0. [Phase 0 — OpenClaw gateway, Codex OAuth, Open-FDD wiring](#0-phase-0--openclaw-gateway-codex-oauth-open-fdd-wiring)
1. [Run Open-FDD on the host](#1-run-open-fdd-on-the-host)
   - [1b) Desired workflow — AI vs manual](#1b-desired-workflow--ai-vs-manual)
2. [OpenClaw / Docker as HTTP client to the host](#2-openclaw--docker-as-http-client-to-the-host)
3. [Quick reference (URLs & logs)](#3-quick-reference-urls--logs)
4. [Prompt — first-time smoke](#4-prompt--first-time-smoke)
5. [Prompt — Phase 2](#5-prompt--phase-2)
6. [DIY BACnet server contract](#6-diy-bacnet-server-contract)
7. [Prompt — BACnet wiring](#7-prompt--bacnet-wiring)

---

## 0) Phase 0 — OpenClaw gateway, Codex OAuth, Open-FDD wiring

Do this **after** the Open-FDD bridge + MCP + UI are up ([§1](#1-run-open-fdd-on-the-host)) so URLs and health checks succeed.

### 0a) Install and onboard OpenClaw

- Install the **OpenClaw** CLI per [OpenClaw Getting started](https://docs.openclaw.ai/start/getting-started) (**Node 22.14+ minimum, Node 24 recommended**).
- Run **`openclaw onboard`** (optionally **`--install-daemon`**) so `~/.openclaw/openclaw.json` and the gateway exist.
- Start the gateway (example): **`openclaw gateway --port 18789 --verbose`** — default port is often **18789**.

### 0b) ChatGPT / Codex subscription auth (same OAuth path as OpenClaw)

- If the browser shows a message about **enabling device code for Codex** or **`codex login --device-auth`**, turn on **device code authorization for Codex** in **ChatGPT settings** (personal) or ask a **workspace admin** (Business / Enterprise). See **[OpenAI Codex authentication](https://developers.openai.com/codex/auth/)** — Open-FDD’s **Open-FDD Claw → Start sign-in** uses the same device flow as the Codex CLI.
- Run **`openclaw models auth login --provider openai-codex`** and complete the browser/device flow.
- Optional: merge an **`auth.profiles`** / **`auth.order`** block for **`openai-codex:default`** into `openclaw.json` so subscription models are explicit (see **[Open FDD Claw architecture — reference fragment](../docs/open-fdd-claw-architecture.md)**).
- Default agent model can stay on an **`openai-codex/<model>`** ref per [OpenClaw OpenAI provider docs](https://docs.openclaw.ai/providers/openai).

### 0c) OpenAI-compatible HTTP on the gateway (for Python / other clients)

If you want **`open_fdd.gateway.openclaw_chat.OpenClawGatewayChatClient`** or any OpenAI-style client to call **through** the gateway (so **Codex OAuth stays in OpenClaw**), enable chat completions in OpenClaw config:

```json5
{
  gateway: {
    http: {
      endpoints: {
        chatCompletions: { enabled: true },
      },
    },
  },
}
```

See [OpenClaw: OpenAI chat completions](https://docs.openclaw.ai/gateway/openai-http-api). Call **`POST http://127.0.0.1:18789/v1/chat/completions`** with **`Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>`** (or `gateway.auth.token`) and header **`x-openclaw-model: openai-codex/<model>`**; request body uses **`model: "openclaw/default"`** per that doc.

Set on the host where Python runs: **`OFDD_OPENCLAW_GATEWAY_URL`**, **`OFDD_OPENCLAW_GATEWAY_TOKEN`**, optional **`OFDD_OPENCLAW_BACKEND_MODEL`** (defaults to **`openai-codex/gpt-5.5`** in code).

### 0d) MCP / Open-FDD automation surface

- **`open-fdd-mcp-rag`** on **8090** is **REST** (`GET /manifest`, `POST /tools/search_docs`, …), not yet a native Streamable HTTP MCP server. Configure the agent with these **URLs** (prompts / `TOOLS.md` / fetch), or add a **small MCP adapter** and then register it under **`mcp.servers`** in `openclaw.json` (see architecture doc).
- **Copy skills** from this repo **`contrib/openclaw-skills/`** into **`~/.openclaw/workspace/skills/`** (see **`contrib/openclaw-skills/README.md`**).

### 0e) Safe defaults (routing + security) for production-like operation

These defaults are strongly recommended before unattended cron automation:

1. **Model routing policy**
   - Keep two OpenClaw agents: `simple` and `complex`.
   - In Open-FDD, route by task class with `open_fdd.gateway.openclaw_chat.OpenClawGatewayChatClient.complete_for_task(...)`.
   - Default class should be **simple** unless signals match complex diagnostics.
2. **Gateway auth**
   - Treat `OPENCLAW_GATEWAY_TOKEN` as an **operator secret**, not an app convenience token.
   - Store it in host secret storage or protected env, never in repo files.
3. **Network posture**
   - Keep gateway and Open-FDD on loopback/private ingress (no direct public exposure).
4. **Tool safety**
   - For non-main sessions, prefer sandbox/allowlists and require approvals for mutating tools (`exec`, config writes, imports).
5. **Audit cadence**
   - Run `openclaw doctor` plus security checks regularly; keep diagnostics export runbooks ready for incidents.

### 0f) Phase 2 reliability + alerting + observability defaults

For scheduled building-watch workflows, require these cron controls:

- Set **failure destination** for every production job (pager/channel/webhook route).
- Enable **skipped-run alerts** for recurring jobs.
- Set an **idempotency key** for jobs that can overlap on retries/restarts.
- Add a **reconcile tag** and **correlation prefix** so run logs can be replayed across OpenClaw -> Open-FDD tools.
- Reconcile regularly with `openclaw cron runs --recent 200` and flag gaps/skips vs expected schedule.

Minimum observability baseline:

- Health checks every 30s:
  - `GET <gateway>/health`
  - `GET <bridge>/health`
  - `GET <mcp>/health`
- SLO starter targets:
  - cron success rate 7d: >=99%
  - skipped-run rate 7d: <1%
  - p95 tool latency: <5s

### 0g) Phase 3 memory governance + MCP adapter + optional subagent lanes

- **Memory governance profile**
  - Keep `MEMORY.md` for durable building truths (equipment, controls, quirks + evidence).
  - Keep daily notes in `memory/*.md` for transient incidents and operator actions.
  - Apply freshness/drift policy (recommended 30-day revalidation for claims).
- **Native MCP adapter**
  - Run `open-fdd-mcp-adapter` for a thin stdio MCP bridge over `open-fdd-mcp-rag`.
  - Set `OFDD_MCP_RAG_REST_BASE` when adapter and REST service are on different hosts.
- **Optional subagent lanes (multi-site scale)**
  - Configure lane env vars:
    - `OFDD_OPENCLAW_ROUTE_SIMPLE_LANES=simple-1,simple-2`
    - `OFDD_OPENCLAW_ROUTE_COMPLEX_LANES=complex-1,complex-2`
  - Pass `site_id` into routing calls so lane selection is deterministic per site.

---

## 1) Run Open-FDD on the host

Requirements: **Python 3.10+**, **Node.js 20+ for the desktop UI** (**Node 22.14+ minimum, Node 24 recommended if also installing OpenClaw CLI**), **git**. Default URLs: bridge **`http://127.0.0.1:8765`**, MCP **`http://127.0.0.1:8090`**, UI (**`start-local`**) uses Vite **`npm run dev`** — typically **`http://127.0.0.1:5173`** (not 8080 unless you change ports).

### 1b) Desired workflow — AI vs manual

**Neither path is deprecated.** Pick what fits the operator.

| Mode | Who starts the stack | Typical flow |
|------|------------------------|--------------|
| **AI-assisted (Open-FDD Claw / OpenClaw)** | Human or agent runs **`start-local.ps1`** or **`start-local.sh`** once on the host (or over SSH). | The AI calls **bridge** endpoints (`/health`, `/assistant/readiness`, `/plots/fdd-frame`, `/plots/share`, …) and points humans to **Plots** readiness links (`plots_quicklinks`, `?fdd=1`, `?share=`). |
| **Fully manual** | Same **`start-local`** scripts; no AI. | Use the **web UI**, **`/docs`**, or **`curl`** / Postman. Optionally export **`GET /model/export`** JSON into ChatGPT or another tool; optional and not tied to OpenClaw. |

**Practical order (both modes):** install deps once → **`start-local`** → wait for **`/health` OK** → ingest or apply site profiles → open **Plots** (or **`GET /assistant/readiness`** for copy-paste links) → run FDD overlay or save a **`POST /plots/share`** handoff for someone else to open **`/plots?share=…`**.

### 1c) Agent-friendly pipeline: ingest → clean → BRICK → plots → FDD

Typical Grafana CSVs keep **units in cells** (`69.5 °F`, `17.8 psi`). Open-FDD stores those as strings until you coerce them.

| Step | Bridge (or MCP tool) | Notes |
|------|------------------------|--------|
| 1. Ingest | **`POST /ingest/csv`** or **`POST /ingest/csv/upload`** | UTF-16 tab + `ts` column supported. |
| 2. Preview clean | **`POST /timeseries/clean-metrics`** with **`commit: false`** | Returns **`suggested_columns`**, **`preview_before`**, **`preview_after`**. |
| 3. Commit clean | Same body with **`commit: true`** | **Purges** Feather for that `site_id` + `source`, writes one cleaned frame. Destructive. |
| 4. BRICK / model | **`GET /model/export`**, **`POST /model/import`**, **`POST /model/ttl/sync`**, or **`POST /assistant/apply-site-profiles`** | Map `external_id` to BRICK types for rule column resolution. |
| 5. Rules (shared with UI) | **`GET /rules`**, **`GET /rules/export-json`**, **`PUT /rules/{file}.yaml`**, **`POST /rules`** | Same managed pack as **FDD Rule Setup** in the desktop UI; export includes raw YAML plus parsed JSON per file. |
| 6. Plots + FDD | **`POST /plots/fdd-frame`**, **`POST /rules/run`**, **`POST /plots/share`** | Bounds / flatline rules expect **numeric** sensor columns. |

MCP (action tools): **`bridge_timeseries_clean_metrics`**, **`bridge_rules_list`**, **`bridge_rules_export_json`**, **`bridge_rules_put`** (see MCP `/manifest`).

Agents should **not** assume they started the UI until **`/health`** succeeds; **`ERR_CONNECTION_REFUSED`** means the gateway is down or the wrong URL/port.

### Windows (recommended here)

PowerShell at repo root — **first time** create a venv, install Python + UI deps, build the MCP index, then launch:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # if scripts are blocked
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -e ".[dev,desktop]"
cd apps\desktop-ui; npm install; cd ..\..
python scripts\build_mcp_rag_index.py --output stack\mcp-rag\index\rag_index.json
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

`start-local.ps1` opens **separate** PowerShell windows for gateway, MCP RAG, and **`npm run dev`** for the UI. Use the Vite URL printed in the UI window (often **`http://127.0.0.1:5173`**).

- **LAN / other PCs:** `powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -LanHost <this-pc-ip>` (equivalent Bash: `bash scripts/start-local.sh --lan-host <this-pc-ip> all`). This sets bridge/MCP listen (`0.0.0.0`), private-LAN CORS, and bridge/MCP/UI public-base URLs; allow **8765**, **8090**, and your **UI port** in Windows Firewall.
- **Docker on same machine will call the host** — see [§2](#2-openclaw--docker-as-http-client-to-the-host); you may need the bridge/MCP to listen on **`0.0.0.0`** (`OFDD_BRIDGE_HOST`, `OFDD_MCP_LISTEN_HOST`) so `host.docker.internal` can connect.

**Git Bash / WSL:** use `bash scripts/start-local.sh`; clone under Linux filesystem in WSL (`~/open-fdd`) for better I/O than `/mnt/c/...`. Background services log to **`stack/local-data/logs/*.log`**. The script prints **UI / Plots / readiness / health** URLs and waits on **`curl`** or **`wget`** for **`/health`** (install **`curl`** for the wait loop).

### macOS

```bash
brew install python@3.12 node@20 git   # or equivalent
cd open-fdd
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,desktop]"
cd apps/desktop-ui && npm install && cd ../..
python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json
bash scripts/start-local.sh
```

### Linux / Raspberry Pi (native)

Install `python3`, `python3-venv`, `python3-pip`, `build-essential`, `git`, `curl`, and **Node 20+** (NodeSource or nvm if distro Node is too old; use **Node 22.14+** if installing OpenClaw CLI on the same host). Then the same `bash` flow as macOS.

On a **Pi**, if the browser is on another device, set the bridge URL before launch, e.g.  
`OFDD_BRIDGE_URL=http://<pi-lan-ip>:8765 bash scripts/start-local.sh`.

**RAM:** `npm install` / `npm run dev` can need **~1–2 GB** free; add swap on low-RAM boards.

### Optional: slim Linux container (CI only)

For **automated tests or CI**, not for co-hosting inside OpenClaw: use a normal Linux image with bash, git, python3, **Node 20+** (or **Node 22.14+** if the same image also installs OpenClaw CLI), then the same venv + `pip install -e ".[dev,desktop]"` + `npm install` + `start-local.sh` steps. Set `NPM_CONFIG_PRODUCTION=false` if the image sets `NODE_ENV=production`. If `tsc: not found`, delete `apps/desktop-ui/node_modules` and re-run `npm install`.

### Loopback typo

Use **`127.0.0.1`** (four octets), not **`127.0.1`**.

---

## 2) OpenClaw / Docker as HTTP client to the host

OpenClaw’s **gateway** listens on **18789** (etc.); it does **not** run Open-FDD for you in this setup.

1. **Start Open-FDD on Windows** (or WSL/macOS) with **`start-local`** (or manual gateway + MCP) **before** agents need CSV/MCP/bridge.
2. From a **container on Docker Desktop** (Windows/Mac), the host is usually  
   **`http://host.docker.internal:8765`** (bridge), **`http://host.docker.internal:8090`** (MCP).  
   Configure whatever OpenClaw/tooling uses for “Open-FDD base URL” / MCP URL to those values (or your host LAN IP on Linux Docker without Desktop).
3. **Windows Firewall:** allow inbound TCP on **8765**, **8090**, and your **UI dev port** (often **5173**) if tools outside localhost connect.
4. **Binding:** if curls from a container get empty replies, ensure the bridge and MCP bind **`0.0.0.0`** on the host for those ports, e.g.  
   `OFDD_BRIDGE_HOST=0.0.0.0` and `OFDD_MCP_LISTEN_HOST=0.0.0.0` in the environment **before** starting `open-fdd-desktop-bridge` / `open-fdd-mcp-rag`. Set **`OFDD_BRIDGE_URL`** (or **`start-local`’s `-BridgeUrl`**) to whatever **your browser** uses (`http://127.0.0.1:8765` on the host, or the LAN IP). Vite’s dev server binds so other machines can reach it when needed; open the firewall for the UI port if required.

**WSL:** if Open-FDD runs on **Windows** and OpenClaw in **Docker Desktop**, prefer **`host.docker.internal`** from the container to hit the Windows stack. If both stacks run **inside WSL**, use `127.0.0.1` from the same network namespace or the WSL IP from Windows as documented for your setup.

---

## 3) Quick reference (URLs & logs)

| Service | Default (same machine) |
|--------|-------------------------|
| Web UI (Vite dev via `start-local`) | `http://127.0.0.1:5173` (see terminal output) |
| Bridge API + `/docs` | `http://127.0.0.1:8765` |
| MCP RAG | `http://127.0.0.1:8090` |

**Readiness / plot deep links:** `GET /assistant/readiness` uses **`OFDD_UI_PUBLIC_BASE`** (both `start-local` scripts default it to the Vite URL above) so links match the UI. If you omit it, the bridge falls back to **`OFDD_UI_PORT`** (see gateway CORS defaults).

From **Docker client to Windows host:** replace host with `host.docker.internal` (see §2).

Logs: **`bash scripts/start-local.sh`** (role `all`) writes **`stack/local-data/logs/gateway.log`**, **`mcp-rag.log`**, **`desktop-ui.log`**. On Windows, **`start-local.ps1`** opens separate windows — watch those terminals (no repo-root `.openfdd-*.log` files).

- Bash roles: `bash scripts/start-local.sh` or `bash scripts/start-local.sh gateway` or `bash scripts/start-local.sh --lan-host 192.168.1.10 all` for a private-LAN dashboard (same intent as PowerShell `-LanHost`).
- PowerShell: `powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -Role gateway` (see `scripts/README.md`)

---

## 4) Prompt — first-time smoke

```text
You are helping me manually smoke-test Open-FDD on the human's machine (prefer Windows PowerShell + scripts/start-local.ps1, or bash + scripts/start-local.sh on macOS/Linux/WSL).

If the human uses OpenClaw, read section **0) Phase 0** first (gateway, `openclaw models auth login --provider openai-codex`, optional `/v1/chat/completions` enablement, skills under `contrib/openclaw-skills/`, workspace bootstrap Markdown under `contrib/openclaw-workspace/`).

Read scripts/OPENCLAW_RUNBOOK.md section **1) Run Open-FDD on the host** for install hints (**Node 20+ for Open-FDD; Node 22.14+ if also installing OpenClaw CLI**, firewall). OpenClaw-in-Docker is optional and only talks HTTP to the host per section **2)** — do not install Open-FDD inside an OpenClaw container unless the human explicitly asks.

Goal: clone the repo, run start-local so the FastAPI bridge, MCP RAG service, and web UI (Vite dev) start; verify health; ingest a CSV into Feather storage; then exercise AI-assisted data modeling and fault detection (FDD) via the bridge + MCP. Report pass/fail with concrete URLs, curl output snippets, and any stack traces from logs.

Do this in order:

1) Clone and enter the repo
   - git clone https://github.com/bbartling/open-fdd.git
   - cd open-fdd

2) First-time setup (creates .venv, pip install, npm install — may take a few minutes)
   - Windows: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -U pip; pip install -e ".[dev,desktop]"; cd apps\desktop-ui; npm install; cd ..\..
   - Unix: python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -e ".[dev,desktop]" && (cd apps/desktop-ui && npm install && cd ../..)

3) Build the MCP RAG index (otherwise MCP /health may be 503 until an index exists)
   - Windows: .\.venv\Scripts\Activate.ps1  then  python scripts\build_mcp_rag_index.py --output stack\mcp-rag\index\rag_index.json
   - Unix: source .venv/bin/activate && python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json

4) Start bridge + MCP + Vite UI
   - Windows: powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
   - Unix: bash scripts/start-local.sh
   - Wait a few seconds. Logs: Unix — tail stack/local-data/logs/gateway.log stack/local-data/logs/mcp-rag.log stack/local-data/logs/desktop-ui.log; Windows — check the three PowerShell windows.

5) Health checks (must succeed on the same host as the processes)
   - curl -sS http://127.0.0.1:8765/health
   - curl -sS http://127.0.0.1:8090/health   (MCP: MUST be 127.0.0.1 — http://127.0.1:8090 is invalid and will fail)
   - curl -sS http://127.0.0.1:5173/ | head -n 5   (Vite dev default; if connection refused, read the UI window for the actual port)
   - MCP /health JSON may include mcp_listen_hint and url_warnings if OFDD_MCP_OFDD_API_URL was mistyped.

6) Tell the human the UI URL (e.g. http://127.0.0.1:5173). If agents run in Docker on the same PC, remind them of http://host.docker.internal:8765 and §2 of the runbook.

7) CSV ingest (Feather)
   - Create a tiny CSV in /tmp (Unix) or a temp path (Windows) with columns including a parseable timestamp (prefer header `timestamp`) and at least one numeric column (e.g. oat or SAT).
   - Create a site: POST http://127.0.0.1:8765/sites JSON {"name":"Smoke Site"} — capture site id from response.
   - Ingest via multipart upload: POST http://127.0.0.1:8765/ingest/csv/upload with form fields site_id=<id>, source=csv, file=@<path-to-csv>
   - Verify: GET http://127.0.0.1:8765/plots/frame?site_id=<id>&source=csv&limit=50

8) MCP validation (read tools)
   - curl -sS http://127.0.0.1:8090/manifest | head
   - POST http://127.0.0.1:8090/tools/search_docs with JSON {"query":"ingest csv","top_k":3} — expect JSON with hits.

9) Optional: MCP “action” tools (bridge proxy) — only if we set a shared secret
   - export OFDD_MCP_ENABLE_ACTION_TOOLS=true
   - export OFDD_MCP_OFDD_API_KEY=smoke-test-key
   - Restart MCP if you changed env after start; then POST /tools/bridge_health with header Authorization: Bearer smoke-test-key (expect JSON). Note: the desktop bridge must accept the same key if bridge auth is enabled; default local bridge often has no key — if calls fail, document and skip action tools.

10) AI-assisted data modeling (via bridge, human can mirror in UI)
   - GET http://127.0.0.1:8765/model/export — confirm sites/equipment/points structure.
   - Optionally POST /model/import with a small valid payload (or guide the human to use the Data Model / CSV import UI to attach points).
   - POST http://127.0.0.1:8765/data-model/sparql with JSON {"query":"PREFIX brick: <https://brickschema.org/schema/Brick#> SELECT ?s WHERE { ?s a brick:Site } LIMIT 5"} — expect bindings or empty graph, not 500.

11) FDD / rules (light touch)
   - Ensure default rules exist or POST /rules/defaults/install if available in this revision.
   - POST /rules/run with site_id, source=csv, rules_path from GET /rules, small chunk_rows if needed — confirm input_rows/output_rows in JSON.

Deliverable: a short checklist table (step → pass/fail), any defects to open as GitHub issues, and exact commands the human should re-run. Stop if a step fails; do not guess secrets.
```

---

## 5) Prompt — Phase 2

```text
You are continuing Open-FDD validation on the human's host (Windows: start-local.ps1; Unix: start-local.sh). The repo path is wherever they cloned it (e.g. C:\Users\...\open-fdd or ~/open-fdd) — do not assume /home/node/.openclaw/workspace unless the human says Open-FDD lives there.

Goal: (1) git pull latest master (or the branch the human names), (2) refresh deps/build only if needed, (3) start or verify bridge + MCP + Vite UI, (4) prove dashboard-equivalent flows: site + CSV upload + plots + merged time-series + model export/SPARQL + default rules + FDD. Report pass/fail with URLs, curl snippets, and log tails. Stop on first hard failure unless the human asks to continue.

Do in order:

0) Paths and update
   - cd to the open-fdd repo root.
   - git status && git fetch origin && git pull origin master   (or: git pull origin <branch> if the human specifies another branch)
   - If start-local.sh fails with CRLF errors on Linux: dos2unix scripts/start-local.sh 2>/dev/null || sed -i 's/\r$//' scripts/start-local.sh

1) Dependencies / stack (skip heavy steps if unchanged and last run was recent)
   - If pyproject.toml, package-lock.json, or launcher scripts changed, or UI/build fails: re-run venv activate + pip install -e ".[dev,desktop]" + (cd apps/desktop-ui && npm install)
   - If MCP index missing or stale: activate venv, then python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json
   - Start services: bash scripts/start-local.sh   OR   powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
   - If the human's browser needs a different bridge base (LAN), use OFDD_BRIDGE_URL or start-local -BridgeUrl accordingly.
   - Logs: Unix — tail stack/local-data/logs/*.log; Windows — check service windows.

2) Health
   - curl -sS http://127.0.0.1:8765/health
   - curl -sS http://127.0.0.1:8090/health   (exact host: 127.0.0.1 — NOT 127.0.1)
   - curl -sS http://127.0.0.1:5173/ | head -n 5   (or the Vite port shown in the UI terminal)

3) Site + CSV (same as UI “upload”)
   - POST http://127.0.0.1:8765/sites with JSON {"name":"Phase2 Site"} — save site_id.
   - Create a small CSV with a parseable timestamp column (header `timestamp` preferred) and numeric metrics. For a quick FDD smoke aligned with bundled AHU/VAV rules, include columns the defaults expect OR document a minimal CSV and any column_map / rules_path limits.
   - POST multipart http://127.0.0.1:8765/ingest/csv/upload — form: site_id=<id>, source=csv, file=@<path>
   - GET http://127.0.0.1:8765/plots/frame?site_id=<id>&source=csv&limit=20 — expect rows/columns JSON.

4) Merged time-series (multi-driver merge-on-read; no merged Feather file)
   - GET http://127.0.0.1:8765/plots/site-frame?site_id=<id>&sources=csv,weather,onboard,bacnet&limit=50 — expect JSON with "sources" listing drivers that had data (weather may be empty until ingest).
   - Optional: POST http://127.0.0.1:8765/ingest/weather with JSON {"site_id":"<id>","days_back":1} if env/lat/long is set; re-hit plots/site-frame and note new columns like *_weather.
   - Optional: POST http://127.0.0.1:8765/timeseries/query with JSON joining multiple sources (see OpenAPI /docs for TimeseriesQueryBody: sources, join_on_timestamp, join_how).

5) Data modeling (API parity with dashboard)
   - GET http://127.0.0.1:8765/model/export — confirm sites/points.
   - POST http://127.0.0.1:8765/data-model/sparql with a small SELECT (e.g. list brick:Site) — must not 500.

6) FDD
   - GET http://127.0.0.1:8765/rules/defaults and POST /rules/defaults/install if needed; attach rule pack to site if the API exists (see /docs).
   - Single source: POST http://127.0.0.1:8765/rules/run with JSON including site_id, source "csv", rules_path from GET /rules (or installed defaults path), optional start_ts/end_ts. Expect input_rows, output_rows, fault_totals, load_mode "single".
   - Merged drivers: POST /rules/run with JSON including "sources": ["csv","weather"] and join_how "outer" if desired. Expect load_mode "merged" and sources list; suffixed columns (e.g. sat_csv) when multiple drivers contribute — rules must match or use column_map.

7) Deliverable
   - Table: step → pass/fail → evidence.
   - One paragraph: “Ready to drop CSV in dashboard?” — yes if health + upload + plots/frame succeed; FDD if /rules/run returns 200 with sensible rows; note ports, merge suffixes, column names vs default rules.

Constraints: use 127.0.0.1 (not 127.0.1). Do not invent API keys. Do not pkill broad patterns that kill your own shell.
```

### Phase 2 — quick notes (human)

| Topic | Detail |
|--------|--------|
| **Dashboard CSV** | Ready when **`/health`**, **`/ingest/csv/upload`**, **`/plots/frame`** work; open the Vite URL from **`start-local`** (often **`http://127.0.0.1:5173`**) or your chosen **`-BridgeUrl`** / firewall setup. |
| **Default-bundle FDD** | Needs CSV columns (or **column_map**) aligned with bundled YAML. |
| **Merged `/rules/run`** | Use **`"sources": ["csv","weather",...]`**; with 2+ contributing drivers, metrics are **`metric_sourcetag`**. |

---

## 6) DIY BACnet server contract

Open-FDD does **not** speak BACnet on the wire. It calls your **[DIY BACnet Server](https://github.com/bbartling/diy-bacnet-server)** (or a compatible gateway) over **HTTP JSON-RPC** in `open_fdd/platform/drivers/bacnet_driver.py`.

**If paths or JSON differ**, paste **OpenAPI/Swagger** so the agent can diff against this contract.

### RPC

- **Base URL** (no trailing slash), reachable from the **bridge** process (same host/LAN as the bridge).
- **`POST {base}/client_read_multiple`**
- **Headers:** `Content-Type: application/json`, `accept: application/json`; optional `Authorization: Bearer <api_key>`.
- **Body (JSON-RPC 2.0):**

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "client_read_multiple",
  "params": {
    "request": {
      "device_instance": 123456,
      "requests": [
        {
          "object_identifier": "analog-input,1",
          "property_identifier": "present-value"
        }
      ]
    }
  }
}
```

- **`device_instance`:** parsed from each model point’s `bacnet_device_id`.
- **Response:** `result.data.results` list, same order as `requests`; each item has a coercible **`value`**. JSON-RPC **`error`** = failure for that batch.

### Model points (pollable)

| Field | Example | Notes |
|--------|---------|-------|
| `site_id` | site UUID | |
| `external_id` | `sat` | Column name in the BACnet Feather row. |
| `bacnet_device_id` | `device,123456` or `123456` | Integer device instance. |
| `object_identifier` | `analog-input,1` | Sent to `requests[].object_identifier`. |
| `polling` | `true` | `"false"` / `"0"` disables. |

Optional: `brick_type`, `fdd_input`, `unit`.

If no qualifying points: ingest returns **success: false** (*No BACnet points with polling=true…*).

### Bridge steps

1. `POST /sites` → `site_id`
2. `POST /model/import` with BACnet points (see **`http://127.0.0.1:8765/docs`**)
3. `POST /config/bacnet` — `server_url`, `site_id`, optional `api_key`, polling `enabled` / `interval_seconds`
4. `POST /ingest/bacnet` — `site_id`, optional `server_url` / `api_key`
5. `GET /config/drivers/health`, `GET /config/bacnet`

**Desktop how-to:** [docs/howto/desktop_app.md](../docs/howto/desktop_app.md) (BACnet curl examples).

---

## 7) Prompt — BACnet wiring

```text
You are wiring Open-FDD desktop bridge BACnet scrape to a DIY BACnet HTTP gateway.

Inputs the human provides (ask if missing):
- Bridge base URL (default http://127.0.0.1:8765)
- DIY server base URL (http/https, reachable FROM the bridge process)
- Optional API Bearer token for the DIY server
- site_id (or create site via POST /sites)
- Whether model points already exist with bacnet_device_id, object_identifier, external_id, polling

Use scripts/OPENCLAW_RUNBOOK.md section "6) DIY BACnet server contract" (POST {diy}/client_read_multiple, method client_read_multiple).

Steps:
1) curl bridge GET /health
2) GET /config/bacnet — note current server_url
3) If the human supplied Swagger/OpenAPI for the DIY server, compare to the runbook contract; list mismatches before ingest.
4) POST /config/bacnet with enabled false first; set server_url, site_id, api_key; GET /config/bacnet to confirm
5) Ensure model has at least one BACnet point for site_id (POST /model/import if needed — use the runbook table)
6) POST /ingest/bacnet with site_id and server_url (and api_key if required)
7) Report JSON (success, rows, devices_polled, points_polled, error). On failure, curl the DIY server with the same JSON-RPC body (redact secrets) and paste status + body snippet
8) Optional: enable polling POST /config/bacnet enabled true; wait one interval; GET /config/drivers/health

Stop on hard network/HTTP errors; do not guess device/object ids.
```
