---
title: MCP server
layout: default
nav_order: 10
parent: AI
---

# Open-FDD MCP server

FastMCP agent interface over the **operator bridge** — not a parallel FDD stack.

## Modes

| Mode | `OFDD_MCP_MODE` | Site resolution |
|------|-----------------|-----------------|
| Edge | `edge` | `OPENFDD_BRIDGE_BASE_URL` (default `http://127.0.0.1:8765`) |
| Portfolio | `portfolio` | `portfolio/sites.json` + optional `site_id` per tool |

**RCx Central** (`:8050` Dash, `:8060` API) is a **separate HTTP stack** — not the MCP server. Agents doing RCx overview, FDD preset tables, or DOCX reports should call Central API (`/api/central/*`) or use the Dash; see [RCx Central agent guide](../agent-skills/rcx-central-dash-agent.md).

Acme production edge runs **without** MCP (`enable_mcp: false`). Run MCP centrally and call `http://100.122.106.124` via Tailscale, or use RCx Central with Edge Connections registry.

## Transport

| Transport | Env | Use |
|-----------|-----|-----|
| Streamable HTTP | `OFDD_MCP_TRANSPORT=streamable-http` (default in Docker) | `http://127.0.0.1:8090/mcp` |
| Stdio | `OFDD_MCP_TRANSPORT=stdio` | Cursor / Claude Desktop |

Legacy bridge doc search: `POST /tools/search_docs` on `:8090` (unchanged).

## Human approval

These tools require `human_approved=true`:

- `save_rule`
- `apply_fdd_tuning`
- `run_fdd_batch`

MCP does not command BACnet writes — only Open-FDD bridge APIs.

## Client examples

**Cursor** (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "open-fdd": {
      "command": "python",
      "args": ["-m", "mcp_server.run"],
      "env": {
        "PYTHONPATH": "/path/to/open-fdd/workspace:/path/to/open-fdd/workspace/api",
        "OPENFDD_REPO_ROOT": "/path/to/open-fdd",
        "OFDD_MCP_TRANSPORT": "stdio",
        "OFDD_MCP_MODE": "portfolio",
        "OFDD_PORTFOLIO_SITES_PATH": "/path/to/open-fdd/portfolio/sites.json"
      }
    }
  }
}
```

**HTTP** (bensserver dev stack):

```bash
docker compose -f docker/compose.dev.yml up -d mcp-rag
curl -fsS http://127.0.0.1:8090/health
```

## Site registry example

```json
{
  "sites": [
    {
      "site_id": "acme",
      "name": "Acme GL36 Lab",
      "base_url": "http://100.122.106.124",
      "username": "integrator"
    }
  ]
}
```

Store passwords in env or OS keychain — not in git.

## RCx Central (not MCP)

| Service | Default URL | Agent docs |
|---------|-------------|------------|
| Central API | `http://127.0.0.1:8060` | [central-api.md](../portfolio/central-api.md) |
| RCx Dash | `http://127.0.0.1:8050` | [rcx-central-dash-agent.md](../agent-skills/rcx-central-dash-agent.md) |

MCP `portfolio_rollup` hits Edge `/api/building/portfolio-rollup` per site. RCx `GET /api/central/overview/{site_id}` adds Dash KPIs, fault pie (with [short fault descriptions](../fault-codes/short-lookup.md)), and mechanical narrative from FDD presets.

## Fault code labels (agents)

Use fixed lookup — do not paraphrase codes in UI copy:

- Docs: [fault-codes/short-lookup.md](../fault-codes/short-lookup.md)
- Python: `portfolio/central/fault_code_lookup.py`
- Edge API: `GET /api/faults/catalog`

## Doc RAG refresh

After editing `docs/` consumed by MCP search:

```bash
./scripts/build_mcp_rag_index.sh
```

- `workspace/mcp_server/` — FastMCP tools, resources, prompts
- `workspace/mcp_rag/retrieval.py` — RAG index (rebuild separately)
- Docker image `openfdd-mcp-rag` — compatibility name; runs unified server

## Module layout
