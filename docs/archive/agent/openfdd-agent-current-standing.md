# Agent runtime status (3.2.x)

What is shipped today vs legacy UI stubs (Ollama, Python MCP-RAG).

## Authoritative

| Item | State |
|------|-------|
| Runtime | Rust `openfdd-edge` + React dashboard |
| Image | `ghcr.io/bbartling/openfdd-edge-rust` (`3.2.3`, `latest`) |
| Services | `openfdd-bridge`, `openfdd-commission`, `openfdd-haystack-gateway` |
| Auth | JWT + RBAC from `workspace/auth.env.local` |
| Historian / FDD | Arrow/Feather + DataFusion SQL |
| Model queries | SPARQL over Haystack RDF projection |
| Agent HTTP | `GET /api/agent/tools`, REST catalog |
| MCP | `openfdd-mcp` stdio sidecar (read-first) |
| Built-in Ollama | Not required — UI placeholders only |

## External orchestration

| Role | Tooling |
|------|---------|
| Runtime | Open-FDD Rust edge |
| Planning / PRs | Cursor, Codex, OpenClaw (LAN) |
| MCP | `openfdd-mcp` with JWT |
| Optional LLM | Local Ollama for doc Q&A only |

## Legacy (verify before use)

| Signal | Interpretation |
|--------|----------------|
| Agent tab / “Validate with Ollama” | Deferred UI |
| `GET /openfdd-agent/building-insight` | Rust stub |
| Python `openfdd-mcp-rag` GHCR workflow | Legacy; use `rust-ghcr.yml` |
| `edge_bootstrap.sh` in old docs | Use `openfdd_rust_edge_bootstrap.sh` |

## Model routing for repo agents

**Simple:** single test failure, one HTTP status, fmt/lint.

**Complex:** auth/RBAC, multi-container issues, deploy scripts, any field-bus write.

## Related

- [openfdd-agent-architecture.md](openfdd-agent-architecture.md)
- [openfdd-mcp-tool-contract.md](openfdd-mcp-tool-contract.md)
- [../ai-agent/README.md](../ai-agent/README.md)
