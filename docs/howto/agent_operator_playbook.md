---
title: Agent & operator playbook (bridge + MCP)
parent: How-to Guides
nav_order: 12
---

# Agent & operator playbook (bridge + MCP)

Use this page as **retrieval fodder** for assistants: it ties **human goals** on the Open-FDD **desktop bridge** to **HTTP routes**, **MCP RAG** (`POST /tools/search_docs`, `POST /tools/search_api_capabilities` on the MCP REST server), and **execution** (Codex on the bridge host, UI actions). Rebuild the MCP index after editing: `python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json`, then **restart `open-fdd-mcp-rag`** (or re-run **`start-local`** after stopping the old MCP process) so the server reloads the file—see **[Desktop app — Restarting start-local and MCP](desktop_app#restarting-start-local-and-mcp-important)**.

**Defaults:** bridge `http://127.0.0.1:8765`, MCP RAG `http://127.0.0.1:8090`, UI `http://127.0.0.1:5173` (override with env).

**Where Codex writes files:** new scripts and helpers go under **`toolshed/scratch/`** in the workdir (gitignored); operators promote keepers to **`toolshed/published/`**. See **[Toolshed](toolshed)**.

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
- **UI copy:** `apps/desktop-ui/src/lib/llm-prompts.ts` — keep in sync for human-facing redesign flows.
- **Bridge assistant route:** search OpenAPI for `data-model`, `openclaw`, `assistant` — e.g. `POST /assistant/data-model-openclaw` (machine JSON output).
- **SPARQL / BRICK context:** `docs/bacnet-rdf-and-brick.md`, `docs/column_map_resolvers.md`.
- **Execution:** exports via `GET /model/export`; imports via documented import routes; never invent `site_id` — use `GET /sites` or readiness.

---

## FDD (fault detection) and tuning

**Human goal:** run rules, interpret faults, tune thresholds / schedules / weather gates.

- **Rules:** YAML under desktop rules root; `POST /rules/run` (or batched variants per OpenAPI) with **`commit: false`** where supported for previews.
- **Cookbook:** `docs/expression_rule_cookbook.md`, `docs/rules/overview.md`.
- **Plots + FDD overlay:** `POST /plots/fdd-frame` — combine time series with fault columns for visualization.
- **Tuning loop:** adjust YAML → preview run → compare episode counts / `fault_totals` in plot payloads → commit when satisfied.
- **Execution:** Codex can edit rule files in the **repo workdir** if filesystem policy allows; otherwise use bridge import/export APIs.

---

## MCP action tools (optional writes)

Read-only RAG is always safe. **Proxy writes** (ingest, config) require MCP server env such as **`OFDD_MCP_ENABLE_ACTION_TOOLS`** and **`OFDD_MCP_OFDD_API_KEY`** — see `docs/howto/desktop_app.md`. Without them, assistants should **only** call the bridge directly with operator keys / localhost trust, not assume MCP mutated data.

---

## Built-in Codex agent (local AI chat)

- **Chat:** `POST /openfdd-agent/chat` — message + `workdir` (repo root on bridge). Agent prompt includes bootstrap URLs.
- **Raw Codex:** `POST /local-codex/chat` — thinner harness; same Codex binary.
- **Sign-in:** CLI must be logged in on the bridge host (`codex login`); device OAuth via bridge complements but may not replace CLI credential store — see product docs.

---

## Query hints for `search_docs`

Use short natural queries containing **keywords**: `BACnet driver`, `clean-metrics`, `plots fdd-frame`, `BRICK import_ready_json`, `rules run commit`, `readiness`, `Feather ingest`, `operator playbook`.
