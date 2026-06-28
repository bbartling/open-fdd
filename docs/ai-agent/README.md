# AI agents (Rust edge)

External orchestrators (Cursor, Codex, MCP clients) operate Open-FDD through **JWT REST**, optional **MCP stdio**, and repo scripts. The bridge container does not embed Ollama or Python agents.

**Architecture:** [agent/openfdd-agent-architecture.md](../agent/openfdd-agent-architecture.md) · **MCP:** [agent/openfdd-mcp-tool-contract.md](../agent/openfdd-mcp-tool-contract.md) · **Safety:** [security/agent-safety-boundaries.md](../security/agent-safety-boundaries.md)

## Capabilities

| Area | Actions | API |
|------|---------|-----|
| Health | Stack status, driver poll state | `/api/health/stack`, `/api/agent/tools` |
| Model | Grid, SPARQL, assignments | `/api/model/haystack`, `/api/model/sparql`, `/api/model/assignments` |
| Drivers | BACnet/Modbus/Haystack trees and reads | `/api/bacnet/driver/tree`, `/api/haystack/read` |
| FDD | Draft SQL, test rules, propose bindings | `/api/fdd-rules/*`, `/api/fdd-wires/propose-assignments` |
| MCP | Read-first tools via sidecar | [mcp/README.md](../../mcp/README.md) |

## Session start

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' ~/open-fdd/workspace/auth.env.local | cut -d= -f2- | tr -d '\r')"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg p "$INTEGRATOR_PW" '{username:"integrator",password:$p}')" \
  | jq -r '.token // .access_token')"
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/tools | jq '.tools | length'
```

## Further reading

- [Haystack and assignments](haystack-and-assignments.md)
- [REST API reference](../AI_AGENT_API.md)
- [Assignment model](../ASSIGNMENT_MODEL.md)
- [Verification](../verification/README.md)

## Never

- Delete `workspace/` · `docker compose down -v` · print secrets
- Field-bus writes or rule activation without human approval
- Expose bridge or MCP on the public internet
