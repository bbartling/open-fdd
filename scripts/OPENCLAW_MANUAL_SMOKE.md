# OpenClaw manual smoke: clone → bootstrap → dashboard + MCP → CSV → modeling + FDD

Use this in a **Linux** environment (container shell or VM) with **bash**, **git**, **python3**, **npm**, and network access.

---

## Prompt to paste into OpenClaw

```text
You are helping me manually smoke-test Open-FDD inside this environment (Docker/container or Linux shell).

Goal: clone the repo, run the bootstrap script so the FastAPI bridge, MCP RAG service, and web dashboard all start; verify health; ingest a CSV into Feather storage; then exercise AI-assisted data modeling and fault detection (FDD) via the bridge + MCP. Report pass/fail with concrete URLs, curl output snippets, and any stack traces from logs.

Do this in order:

1) Clone and enter the repo
   - git clone https://github.com/bbartling/open-fdd.git
   - cd open-fdd

2) First-time setup (creates .venv, pip install, npm install — may take a few minutes)
   - bash scripts/bootstrap-desktop.sh --install-deps --no-launch

3) Build the MCP RAG index (otherwise MCP /health may be 503 until an index exists)
   - source .venv/bin/activate
   - python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json

4) Start bridge + MCP + static web UI (default ports)
   - bash scripts/bootstrap-desktop.sh
   - Wait a few seconds, then tail the last lines of: .openfdd-bridge.log .openfdd-mcp.log .openfdd-ui.log

5) Health checks (must succeed)
   - curl -sS http://127.0.0.1:8765/health
   - curl -sS http://127.0.0.1:8090/health
   - curl -sS http://127.0.0.1:8080/ | head -n 5   (should return HTML for the React app)

6) If running inside Docker, ensure ports 8765, 8090, 8080 are published to the host (-p 8765:8765 -p 8090:8090 -p 8080:8080) and tell the human the host URLs to open the dashboard (e.g. http://localhost:8080).

7) CSV ingest (Feather)
   - Create a tiny CSV in /tmp with columns including a parseable timestamp (prefer header `timestamp`) and at least one numeric column (e.g. oat or SAT).
   - Create a site: POST http://127.0.0.1:8765/sites JSON {"name":"Smoke Site"} — capture site id from response.
   - Ingest via multipart upload: POST http://127.0.0.1:8765/ingest/csv/upload with form fields site_id=<id>, source=csv, file=@/tmp/smoke.csv
   - Verify: GET or POST flows that show rows ingested; optionally GET http://127.0.0.1:8765/plots/frame?site_id=<id>&source=csv&limit=50

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

## Quick reference (human)

| Service | URL | Purpose |
|--------|-----|--------|
| Web UI | `http://127.0.0.1:8080` | Dashboard; CSV import / model / plots (uses bridge API). |
| Bridge API | `http://127.0.0.1:8765` | REST + Swagger at `/docs`. |
| MCP RAG | `http://127.0.0.1:8090` | `/manifest`, `/tools/search_docs`, optional action tools. |

Logs in repo root: `.openfdd-bridge.log`, `.openfdd-mcp.log`, `.openfdd-ui.log`.

Bootstrap help: `bash scripts/bootstrap-desktop.sh --help`
