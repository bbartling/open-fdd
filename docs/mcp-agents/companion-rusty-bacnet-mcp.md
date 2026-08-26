---
title: Companion — rusty-bacnet-mcp
parent: MCP Agents
nav_order: 6
---

# Companion: rusty-bacnet-mcp (BACnet debug)

**Use when fieldbus OT gates fail and you need independent BACnet proof on the OT LAN.**  
`openfdd-mcp` talks to **Central REST** — it does **not** send BACnet ReadProperty on the wire.

Production polling stays on **`openfdd-fieldbus`**. [rusty-bacnet-mcp](https://github.com/jscott3201/rusty-bacnet-mcp) is a **read-only diagnostic** MCP on the rusty-bacnet stack.

## When to use

| Situation | Tool |
|-----------|------|
| FDD, historian, edges, MQTT ingest | `openfdd-mcp` → Central |
| Routed MS/TP (device 5007), Who-Is, ReadProperty isolation | rusty-bacnet-mcp on OT subnet |
| Product poll / MQTT publish | `openfdd-fieldbus` only |

## Install (bench)

```bash
cargo install --git https://github.com/jscott3201/rusty-bacnet-mcp bacnet-mcp --features bin
cp examples/bacnet-mcp.json ./bacnet-mcp.json
# Edit transports.bip.broadcast for your OT subnet; keep mcp.read_only true
```

## Cursor snippet (stdio)

```json
{
  "mcpServers": {
    "openfdd": { "...": "see mcp/README.md" },
    "bacnet": {
      "command": "/path/to/bacnet-mcp",
      "args": ["--config", "/path/to/bacnet-mcp.json"]
    }
  }
}
```

## Typical debug flow (B3 / MS/TP)

1. `discover_devices` / `list_known_devices` — confirm router + instance 5007.
2. `read_property` on `analog-input:1173` for device 5007.
3. Compare with `POST /bacnet/read` on fieldbus `:8081`.
4. If MCP succeeds and fieldbus fails → fieldbus seed/config bug. If both fail → OT LAN / router.

## Safety

- Keep **`read_only: true`** unless a human explicitly approves writes.
- Follow [`BACNET_OT_POLICY.md`](../operations/BACNET_OT_POLICY.md) — default **300 s** poll, **60 s** floor, ~**30%** health points on cell sites.
