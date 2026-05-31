---
title: Agent & operator playbook (bridge + MCP)
parent: How-to Guides
nav_order: 12
---

# Agent & operator playbook (bridge + MCP)

Use this page as **retrieval fodder** for assistants: it ties **human goals** on the Open-FDD **operator bridge** to **HTTP routes**, **MCP RAG** (`POST /tools/search_docs` on the MCP REST server), and **execution** (Codex on the bridge host, UI actions). Rebuild the MCP index after editing docs: `./scripts/build_mcp_rag_index.sh`, then restart the stack (`./scripts/run_local.sh restart --ui-skip`).

**Defaults (local `run_local.sh` stack):** dashboard **`http://127.0.0.1/`** when Caddy enabled (else **`http://127.0.0.1:8765/`**), bridge API **`http://127.0.0.1:8765`**, MCP RAG **`http://127.0.0.1:8090`**. Optional Vite HMR: **`http://127.0.0.1:5173`** only with `./scripts/run_local.sh start --dev` (not production parity).

**Where Codex writes files:** new scripts and helpers go under **`workspace/scratch/`** (gitignored); durable FDD rules go to **`workspace/data/rules_py/`** via Rule Lab or `rules.save` — see **[Rule Lab — Python storage](rule_lab_storage)**.

---

## Discovery every session should use

- `GET /health` — bridge up.
- `GET /assistant/readiness` — operator links, plots hints, suggested actions.
- `GET /openapi.json` or `GET /docs` — full API surface.
- `GET http://127.0.0.1:8090/manifest` then `POST http://127.0.0.1:8090/tools/search_docs` — indexed how-tos + OpenAPI chunks.
- `GET /openfdd-agent/context` — merged bootstrap (bridge, MCP, UI, endpoint map) for the built-in Codex agent.

---

## Drivers (BACnet, CSV, weather, ingest)

**Human goal:** pull field data, map columns, run ingest, debug driver health.

- **BACnet:** see `docs/bacnet/index.md`, gateway driver config and health under bridge routes (search OpenAPI for `bacnet`, `driver`).
- **CSV / uploads:** `POST /ingest/csv`, `POST /ingest/csv/upload` — body keys per OpenAPI (`site_id`, `source`, paths or multipart).
- **Model + TTL:** `GET /model/export`, model CRUD under `/sites`, equipment, points; TTL sync env `OFDD_MODEL_TTL_PATH`, `OFDD_MODEL_TTL_MIRROR_PATH`.
- **Execution:** Codex can call `Invoke-RestMethod` / `curl.exe` against the bridge; long-running ingest may need timeouts. Prefer **preview** responses before destructive writes.

---

## Data cleaning & plot-ready metrics

**Human goal:** strings with units (`"84 °F"`) break Plotly / FDD; normalize columns.

- **Readiness on plot frames:** responses may include `recommend_clean_metrics` and per-column hints.
- **Primary API:** `POST /timeseries/clean-metrics` — use **`commit: false`** first (preview), then **`commit: true`** after human confirmation.
- **Plots:** `GET /plots/frame`, `GET /plots/site-frame`, `POST /plots/fdd-frame` — inspect JSON sample + readiness block before tuning rules.
- **Execution:** agent should sequence preview → show diff summary → commit only if operator agrees.

---

## AI-assisted BRICK data modeling

**Human goal:** align `model.json` / TTL with BRICK, preserve IDs, keep `external_id` aligned to Feather/CSV headers, set `fdd_input` where rules need it.

- **Authoritative prompt (API):** `open_fdd/assistant/data_model_redesign_prompt.py` — `DATA_MODEL_REDESIGN_SYSTEM_PROMPT`, `import_ready_json` contract.
- **UI copy:** `workspace/dashboard/src/lib/llm-prompts.ts` — keep in sync for human-facing redesign flows.
- **Bridge assistant route:** search OpenAPI for `data-model` and `assistant` endpoints that return machine JSON output.
- **SPARQL / BRICK context:** `docs/bacnet-rdf-and-brick.md`, `docs/column_map_resolvers.md`.
- **Execution:** exports via `GET /model/export`; imports via documented import routes; never invent `site_id` — use `GET /sites` or readiness.

---

## FDD (fault detection) and tuning

**Human goal:** run Python rules, interpret faults, tune thresholds.

- **Rule Lab (`/rule-lab`):** edit `.py` in the browser; lint/test via `POST /api/playground/lint`, `POST /api/playground/test-rule`, `POST /api/playground/run-script`.
- **On disk:** `workspace/data/rules_store.json` + `workspace/data/rules_py/*.py` — humans and AI share the same files ([Rule Lab storage](rule_lab_storage)).
- **Persist + schedule:** `POST /api/rules/save`, `GET /api/rules/saved`, `GET/PUT /api/rules/saved/{id}/source`, `POST /api/rules/batch`; background loop: `python -m openfdd_bridge.fdd_runner --loop` (started by `run_local.sh`).
- **Column mapping:** Data Model tab (`/data-model`) — drag rules onto points; bridge merges `fdd_input` / BRICK keys into `column_map` at run time.
- **Tuning loop:** adjust Python + `config` → preview in Rule Lab → save → batch run → check building check-engine on `/`.

### AI writing the same Python

- **Chat tab (`/agent`):** `POST /openfdd-agent/chat` — Ollama only; does **not** invoke tools automatically. Use `GET /openfdd-agent/context` for `saved_rules` and tool list.
- **Tool API (agent role):** `POST /openfdd-agent/tool` with `{ "tool": "rules.save", "args": { "name", "code", "fault_code", … } }` — writes the same JSON + `.py` as Rule Lab Save.
- **Run batch from automation:** `{ "tool": "rules.run_batch" }`.
- **Read source:** `GET /api/rules/saved/{id}/source` or open `workspace/data/rules_py/*.py` on the host.

---

## MCP action tools (optional writes)

Read-only RAG is always safe. **Proxy writes** (ingest, config) require MCP server env such as **`OFDD_MCP_ENABLE_ACTION_TOOLS`** and **`OFDD_MCP_OFDD_API_KEY`** — see `docs/howto/desktop_app.md`. Without them, assistants should **only** call the bridge directly with operator keys / localhost trust, not assume MCP mutated data.

---

## Built-in Ollama agent (AI Agent tab)

- **Chat (browser → bridge):** `POST /openfdd-agent/chat` — local Ollama on the bridge host; optional `history` for multi-turn. The dashboard does not call Codex directly.
- **Context:** `GET /openfdd-agent/context` — model summary, saved rules, fault codes, MCP hints, tool catalog.
- **Tools (agent role only):** `POST /openfdd-agent/tool` — `rules.save`, `rules.run_batch`, model CRUD; audited. Chat does not auto-invoke tools.
- **Repo-local shell (no browser):** `openfdd-agent-shell` and `openfdd-wake` run Codex from the checkout with `openfdd.toml`; see **[Skills and agent shell](skills_and_agent)**.

---

## Query hints for `search_docs`

Use short natural queries containing **keywords**: `BACnet driver`, `clean-metrics`, `plots fdd-frame`, `BRICK import_ready_json`, `rules run commit`, `readiness`, `Feather ingest`, `operator playbook`.
