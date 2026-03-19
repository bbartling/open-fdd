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

Security note: when `OFDD_API_KEY` is enabled, all API routes (including `GET /model-context/docs`) require Bearer auth.

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

