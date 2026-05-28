---
name: mcp-doc-retrieval
description: "Builds a REST MCP-style doc and API capability search service over chunked markdown indexes. Use when agents need RAG over docs and bridge OpenAPI hints."
---

# MCP doc retrieval

## When to use

Optional alongside bridge for `search_docs`, `search_api_capabilities`, `get_doc_section`.

## Quick start

1. Chunk `docs/*.md` into JSON index (see `scripts/build_doc_index.py` in this skill).
2. FastAPI on `127.0.0.1:8090` by default; set `OFDD_MCP_RAG_INDEX_PATH`. Only bind `0.0.0.0` when the operator explicitly opts in for LAN/Caddy ingress.
3. Action tools proxy bridge only when `OFDD_MCP_ENABLE_ACTION_TOOLS=true` and API key set.

## Verification

`GET /health`, `POST /tools/search_docs` with `{ "query": "RuleRunner", "top_k": 5 }`.

## Compose

[fastapi-bridge-api](../fastapi-bridge-api/SKILL.md), [local-dev-orchestration](../local-dev-orchestration/SKILL.md)

See [references/REFERENCE.md](references/REFERENCE.md).
