---
name: open-fdd-bootstrap
description: First-run checks for Open-FDD + MCP RAG — bridge health, doc index, API discovery — and human-visible failure reporting.
---

# Open-FDD bootstrap (hit the ground running)

## When to use

- Start of a session or before multi-step FDD / ingest / modeling work.
- Operator asks “is everything up?” or the assistant has not yet verified **bridge + MCP** this session.

## What to run (order)

1. **Bridge** — `GET http://127.0.0.1:8765/health` (or MCP tool **`bridge_health`** if configured). If not OK, **tell the human clearly**: gateway window closed, wrong port, or venv not started — do not invent JSON.
2. **MCP catalog** — `GET http://127.0.0.1:8090/manifest` (no auth for read of manifest in default dev; if 401, use `Authorization: Bearer` from `OFDD_MCP_OFDD_API_KEY`). If connection refused or repeated errors, **tell the human**: MCP RAG not running — re-run `start-local` / `open-fdd-mcp-rag` and ensure port **8090**.
3. **Docs index** — MCP **`search_docs`** with a trivial query (e.g. `open-fdd health`) or **`search_api_capabilities`** with `plots`. If the tool errors about missing index / empty index, **tell the human**: run `python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json` from the repo root (see `scripts/README.md`), then restart MCP.
4. **Handoff** — MCP **`bridge_readiness`** or `GET /assistant/readiness` — gives the same deep links and markdown the **Open-FDD Claw** page uses so guidance matches the UI.

5. **String metrics → Feather** — if plot readiness recommends **`clean-metrics`**, follow skill **`open-fdd-clean-metrics`** (preview → confirm → **`commit: true`** → re-check readiness).

## “Seeing” the React UI

You do **not** receive a live DOM or screen pixels from the operator’s browser unless they paste screenshots or you use a **separate** browser tool. Treat **`/assistant/readiness`** + **`plots_quicklinks`** + known routes (`/plots`, `/openfdd-claw-chat`, `/data-model`, `/csv-import`, `/rule-setup`) as the **shared map** so your suggestions align with what the human sees.

## If context is offline

- **MCP down** → say MCP unreachable; fix stack before relying on `search_docs`.
- **Index missing** → say doc search unavailable; build index and restart MCP.
- **Bridge down** → say Open-FDD API unavailable; fix bridge first.

## References

- `contrib/openclaw-workspace/AGENTS.md`, `TOOLS.md`
- `scripts/OPENCLAW_RUNBOOK.md` §0–§3
- `docs/open-fdd-claw-architecture.md`
