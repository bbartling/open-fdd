---
title: MCP RAG service
parent: Operations
nav_order: 5
---

# MCP RAG service

Open-FDD can run an optional MCP-style retrieval service derived from canonical docs.

## Canonical vs derived context

- Canonical human docs: `docs/` and generated `pdf/open-fdd-docs.txt`.
- Derived AI index: `stack/mcp-rag/index/rag_index.json`.

Never edit index artifacts as source-of-truth documentation.

## Bootstrap

Run:

```bash
./scripts/bootstrap.sh --with-mcp-rag
```

This flow builds docs text when needed, builds retrieval index, and starts the MCP RAG service profile.

For module-focused operations, combine with bootstrap mode:

```bash
./scripts/bootstrap.sh --mode model --with-mcp-rag
```

## Service endpoints

- `GET /health`
- `GET /manifest`
- `POST /tools/search_docs`
- `POST /tools/get_doc_section`
- `POST /tools/search_api_capabilities`
- `POST /tools/get_operator_playbook`

Optional guarded action tools are present but disabled by default via `OFDD_MCP_ENABLE_ACTION_TOOLS=false`.

