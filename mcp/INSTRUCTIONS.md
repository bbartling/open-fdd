# Open-FDD MCP server instructions

Read-first MCP sidecar for the Rust edge bridge. Requires JWT via `OPENFDD_MCP_TOKEN` or unauthenticated `/api/health` only.

## Haystack (Niagara nHaystack)

- URL pattern: `https://<station>/haystack` with **HTTP Basic** (`auth_mode=basic`) — **NOT SCRAM**
- Self-signed TLS: `tls_verify=false` in `workspace/haystack/local.nhaystack.toml`
- Credentials: `OPENFDD_HAYSTACK_USER` / `OPENFDD_HAYSTACK_PASS` (never commit)

## BACnet field reads

Use **commission** API (`OPENFDD_COMMISSION_BASE`, default `http://127.0.0.1:9091`) for OT Who-Is/reads — not bridge host-network.

## Bench setup

See repository doc `docs/agent/bench-driver-setup-wsl-agent.md` for WSL agent workflow, validation script `./scripts/openfdd_drivers_validate.sh`, and parity targets.

## Safety

Phase 2 write tools are **not** implemented. Never log tokens or Haystack passwords.
