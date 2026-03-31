---
title: Open‑Claw Integration
parent: How-to Guides
nav_order: 6
---

# Open‑Claw Integration (external worker)

Open‑FDD does not embed or run an LLM. Instead, you run Open‑Claw (or any OpenAI-compatible agent) externally, and use Open‑FDD’s REST API as the “data + tool” layer. Open‑Claw can be local (same host) or hosted remotely; your agent just needs network access to the Open‑FDD API.

This page shows how to:

1. Fetch platform documentation as model context (`GET /model-context/docs`)
2. Discover HTTP mappings programmatically (`GET /mcp/manifest`)
3. Automate Brick tagging (`GET /data-model/export` → LLM → `PUT /data-model/import`)
4. Tune FDD faults by updating rule YAML files (`/rules/*`) and syncing definitions

Security note: when **auth is required** (`OFDD_API_KEY` and/or Phase 1 app-user login), API routes (including `GET /model-context/docs`) accept **`Authorization: Bearer`** with either the **API key** or a **JWT access token** issued from **`POST /auth/login`**. External HTTP agents normally use the **API key**; browsers use login + JWT. `/auth/*` is exempt from the middleware so login/refresh/logout work.

---

## 1) Model context endpoint (`GET /model-context/docs`)

External agents should fetch Open‑FDD documentation context from:

- `GET /model-context/docs`

Control the output size and retrieval:

- `mode=excerpt` (default): truncated excerpt of `pdf/open-fdd-docs.txt`
- `mode=full`: entire doc file
- `mode=slice&offset=...`: a substring (character offset + `max_chars`)
- `query=...`: keyword-retrieved relevant doc sections (simple lexical matching)

If your agent’s context window is running out, re-fetch context using `query=...` (or `mode=slice`) as needed.

---

## 1b) MCP-style discovery (`GET /mcp/manifest`)

Open-FDD exposes a **small JSON manifest** (not a full MCP stdio/SSE server) at:

- `GET /mcp/manifest`

Use it to wire external workers or a **separate** MCP server you maintain: the manifest lists **resource URIs** (e.g. `openfdd://docs`) and **tool-shaped** entries with `http.method` + `http.path` for:

- Fetching docs (`/model-context/docs`)
- Data-model export/import (`/data-model/export`, `/data-model/import`)
- Capability discovery (`/capabilities`)

Your agent implementation should perform the described HTTP requests with the same **Bearer** token as the rest of the API when auth is enabled.

---

## 1c) Optional MCP RAG sidecar (`--with-mcp-rag`)

Open-FDD can also run an optional MCP-style RAG sidecar built from canonical docs:

- start with `./scripts/bootstrap.sh --with-mcp-rag`
- service: `http://localhost:8090`
- manifest: `GET /manifest`

This sidecar provides retrieval-focused tools over derived index artifacts from `docs/` and `pdf/open-fdd-docs.txt`. By default it is read-oriented; guarded API action tools exist but are disabled unless explicitly enabled with `OFDD_MCP_ENABLE_ACTION_TOOLS=true`.

---

## 1d) Mode-aware orchestration with bootstrap

OpenClaw can orchestrate partial deployments through bootstrap modes:

- `./scripts/bootstrap.sh --mode full` (default)
- `./scripts/bootstrap.sh --mode collector`
- `./scripts/bootstrap.sh --mode model`
- `./scripts/bootstrap.sh --mode engine`

This enables targeted runs (for example model-only SPARQL work or engine-only rule validation) without always launching the full stack.

---

## 1e) OpenClaw on a different machine than Open-FDD (split setup)

OpenClaw does **not** have to run on the same host as Docker / the git clone. A common pattern is **Open‑FDD on a Linux server** and **OpenClaw on a Windows (or other) workstation** on the same **test bench LAN**.

**How OpenClaw-style tests talk to Open‑FDD (HTTP)**

Bench and helper scripts treat Open‑FDD like any other REST client: they read **`OFDD_API_KEY`** from the environment (often after loading a copy of **`stack/.env`** from the Linux host) and send **`Authorization: Bearer <OFDD_API_KEY>`** on each request. They do **not** open a browser, call **`/auth/login`**, or manage HttpOnly cookies — that flow is for the React dashboard only. If the stack has **Phase 1 app-user** auth enabled **without** an **`OFDD_API_KEY`**, those scripts would need a JWT instead (cookie + login); **for automation, keep `OFDD_API_KEY` in `stack/.env` and mirror it into the Windows environment** (or a small `.env` you load before running Python). Product details of the bench live under **`openclaw/`** in the repo; this page only describes how that pattern fits Open‑FDD.

**What the external agent needs**

1. **Shell access to the Linux host** (SSH) if it will run `./scripts/bootstrap.sh`, `pytest`, or edit files in the clone — point OpenClaw’s workspace at that path or mount it. If the agent only drives **HTTP tools**, a full clone on Windows is optional.
2. **Reachable base URL** — from the Windows machine, **`http://localhost:8000` does not reach the Linux server.** Use the host’s **LAN IP or DNS name**:
   - **Direct API:** `http://<open-fdd-host>:8000/...` (paths as in Swagger, e.g. `/sites`, `/data-model/sparql`).
   - **Through Caddy (port 80):** `http://<open-fdd-host>/api/...` for REST paths the UI uses (Caddy strips the `/api` prefix before proxying). Auth endpoints: `http://<open-fdd-host>/auth/...`.
   Bench scripts are usually simplest against **`:8000`** so paths match `/sites` with no prefix. Use **port-forward** or **SSH tunnel** only if you deliberately map remote 8000 to local `localhost`.
3. **Bearer token for REST** — set **`OFDD_API_KEY`** on the bench to the same value as in **`stack/.env` on the Open‑FDD host** (see [Security — Phase 1 auth modes](security.md#frontend-and-api-authentication-phase-1)). Do not commit that file; copy the key out of band. DB passwords and other secrets can stay on the server.
4. **Browser UI from Windows (optional)** — open **`http://<open-fdd-host>/`** (Caddy) or **`http://<open-fdd-host>:5173`** (direct frontend). Sign in at **`/login`** when Phase 1 user auth is configured; the app uses **`VITE_API_BASE=/api`** behind Caddy so API calls stay same-origin. This is **independent** of the Bearer header OpenClaw uses for REST.

**File handoff (`openclaw/issues_log.md`)** — [`HANDOFF_PROTOCOL.md`](../openclaw/HANDOFF_PROTOCOL.md) assumes both Cursor and OpenClaw can read the **same repo tree**. With a split setup, use **git push/pull** (or SSH to one canonical clone) so the lab trail stays in sync.

---

## 2) Automated Brick tagging loop

For automated tagging, use the same underlying workflow as manual export/import:

1. Export the current model:
   - `GET /data-model/export` (optionally `?site_id=...`)
2. Get documentation context for the LLM:
   - `GET /model-context/docs?query=data-model+import` (or a broader query)
3. Ask Open‑Claw to return **import JSON**:
   - Output must match the Open‑FDD import schema: top-level keys `points` and optional `equipment`
4. Validate and import:
   - `PUT /data-model/import` with the validated JSON

Practical prompt pattern for retries:

- If `PUT /data-model/import` returns an error, include the error text in the next LLM prompt and retry (prompt chaining).

---

## 3) “Tune faults” worker loop (rule YAML)

Open‑FDD’s fault definitions are driven by YAML rule files stored under your configured `rules_dir`.

An Open‑Claw worker can update those rules via:

- `GET /rules` (list YAML files and the resolved `rules_dir` path)
- `POST /rules` (upload/overwrite a rule YAML file)
- `POST /rules/sync-definitions` (immediately refresh `fault_definitions` from `rules_dir`)
- `DELETE /rules/{filename}` (delete a YAML file)

Then run FDD so the new rules take effect:

- `POST /run-fdd` (trigger “run now”)
- or `POST /jobs/fdd/run` (async job)

If you need to validate improvements before running the loop, use:

- `POST /data-model/sparql` for SPARQL-based checks
- and/or `GET /faults/definitions` / `GET /faults/active` for runtime state.

---

## 4) Example “worker” prompt for Open‑Claw

Use this as your agent’s system prompt (or as the first instruction in your developer prompt). Replace bracketed placeholders as needed.

```text
You are an Open‑FDD worker for building operators.

Tools you can call:
- Open‑FDD documentation context: GET {{OFDD_BASE_URL}}/model-context/docs
- Data model export: GET {{OFDD_BASE_URL}}/data-model/export
- Data model import: PUT {{OFDD_BASE_URL}}/data-model/import
- Rule YAML management:
  - GET {{OFDD_BASE_URL}}/rules
  - POST {{OFDD_BASE_URL}}/rules
  - POST {{OFDD_BASE_URL}}/rules/sync-definitions
  - DELETE {{OFDD_BASE_URL}}/rules/{filename}
- Validation helpers:
  - POST {{OFDD_BASE_URL}}/data-model/sparql

Context strategy:
- If you need more Open‑FDD details and your context is running out, re-fetch docs context:
  - GET /model-context/docs?query={{SEARCH_TERMS}}&mode=excerpt&max_chars=28000

Brick tagging task:
1) Call GET /data-model/export.
2) Call GET /model-context/docs?query=data-model+import.
3) Produce ONLY valid import JSON: top-level keys `points` and optional `equipment`.
4) Call PUT /data-model/import with the validated JSON.
5) If PUT returns an error, include the error message in your next attempt prompt and retry (prompt chaining).

Fault tuning task:
1) Read current rules: GET /rules and (optionally) GET /rules/{filename}.
2) Propose minimal YAML changes to improve the target fault behavior.
3) Upload updated YAML: POST /rules (overwrite).
4) Sync definitions: POST /rules/sync-definitions.
5) Trigger evaluation: POST /run-fdd (or POST /jobs/fdd/run).
6) Summarize what changed and why.
```

---

## 5) Recommended “context window” behavior

For larger exports and/or multi-step workers:

- Start with `mode=excerpt`
- When you hit a knowledge gap, fetch a smaller targeted subset with `query=...`
- If you still need more, use `mode=slice&offset=...` to walk through the full doc file.

