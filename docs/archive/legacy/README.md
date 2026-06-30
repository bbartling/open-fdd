# Legacy documentation index

Documents and workflows here describe **superseded** Python-era, built-in Ollama, or MCP-RAG concepts. They are kept for archaeology — **do not** treat as the current Rust edge path without cross-checking [agent/openfdd-agent-current-standing.md](../agent/openfdd-agent-current-standing.md).

| Topic | Legacy signal | Current path |
| --- | --- | --- |
| Python FastAPI bridge | Old GHCR `openfdd-bridge` Python image | `ghcr.io/bbartling/openfdd-edge-rust` |
| `openfdd-mcp-rag` container | `.github/workflows/ghcr-multiarch-publish.yml` | MCP deferred — [openfdd-mcp-tool-contract.md](../agent/openfdd-mcp-tool-contract.md) |
| Built-in Ollama runtime | Agent tab, Faults "Validate with Ollama" | Optional local LLM for operators only |
| Rule Lab tab name | Old dashboard nav | SQL FDD rules + FDD Wires |
| `edge_bootstrap.sh` | Some AI doc headers | `openfdd_rust_edge_bootstrap.sh` |

When updating docs, prefer editing current guides under `docs/agent/`, `docs/ai-agent/`, and root `AGENTS.md` rather than deleting legacy references without trace.
