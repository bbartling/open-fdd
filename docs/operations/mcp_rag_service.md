---
title: MCP RAG service
parent: Operations
nav_order: 5
---

# MCP RAG service

**Deprecated:** the **`mcp-rag`** container, **`/mcp/manifest`**, and **`--with-mcp-rag`** were **removed** from the monorepo. Use **`GET /model-context/docs`**, **`GET /openapi.json`**, and Swagger **`/docs`** for agent discovery. The text below is kept only as historical context.

## Canonical vs derived context

- Canonical human docs: `docs/` and generated `pdf/open-fdd-docs.txt`.
- Derived AI index: `stack/mcp-rag/index/rag_index.json`.

Never edit index artifacts as source-of-truth documentation.

## Bootstrap (historical only)

The following **no longer applies** to the default monorepo; the **`mcp-rag`** profile and **`--with-mcp-rag`** flag were removed.

```bash
# REMOVED — do not run; kept for archaeology
# ./scripts/bootstrap.sh --with-mcp-rag
# ./scripts/bootstrap.sh --mode model --with-mcp-rag
```

Use **`GET /model-context/docs`**, **`GET /openapi.json`**, and **`/docs`** on a running FastAPI instance instead.

## Service endpoints

- `GET /health`
- `GET /manifest`
- `POST /tools/search_docs`
- `POST /tools/get_doc_section`
- `POST /tools/search_api_capabilities`
- `POST /tools/get_operator_playbook`

Optional guarded action tools are present but disabled by default via `OFDD_MCP_ENABLE_ACTION_TOOLS=false`.

