---
name: openfdd-bacnet-ot-debug
description: >-
  Use when BACnet Who-Is, ReadProperty, fieldbus OT, MS/TP, or MQTTS ingest
  fails on a LAN bench or edge. Triggers on: BACnet, Who-Is, ReadProperty,
  fieldbus :8081, bacpypes3, rusty-bacnet-mcp, MS/TP, local OT bench, sensor
  smoke, py-bacnet-stacks-playground.
---

# BACnet OT debug (Open-FDD)

`openfdd-mcp` is **Central REST** (FDD/historian). It does **not** replace
wire-level BACnet. **Product OT = `openfdd-fieldbus` + rusty-bacnet (Rust).**
BACpypes3/Python is **troubleshoot-only** — never a production driver.

## Always prove both layers

| Layer | Must pass | Why |
|-------|-----------|-----|
| **Who-Is** | ≥1 I-Am on the OT NIC | BVLL bound; peers reachable |
| **ReadProperty** | Numeric `present-value` on a known object | IPs change; discovery alone is not enough |

Peer addresses on the Mint bench move with DHCP — set `READ_TARGET` / `--target`
from a live Who-Is (do not bake private IPs into product code).

## Where to look (in order)

1. **Product fieldbus (rusty-bacnet)** — `POST http://127.0.0.1:8081/bacnet/whois`
   and read APIs; Who-Is binds `0.0.0.0` + hosted port (`SO_REUSEADDR`, #526).
   Unicast reads use ephemeral ports. Poll is **hard-coded 300 s** — never put
   fieldbus on Railway.
   Policy: [`docs/operations/BACNET_OT_POLICY.md`](../../../docs/operations/BACNET_OT_POLICY.md)
2. **BACpypes3 diagnose-only** (stop fieldbus first if you need host `:47808`)
   - Doc: [`docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md`](../../../docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md)
   - Script: `./scripts/ops/local_bacnet_ot_bench.sh sensor`
   - Python: `scripts/ops/bacpypes3_whois_smoke.py` (`whois` | `read` | `sensor`)
3. **MQTTS pipeline** (containers, no live MS/TP required) —
   `./scripts/ops/local_bacnet_ot_bench.sh pipeline` or
   `scripts/integration/bacnet_mqtt_container_smoke.sh`
4. **Companion rusty-bacnet-mcp** (read-only wire debug) —
   [`docs/mcp-agents/companion-rusty-bacnet-mcp.md`](../../../docs/mcp-agents/companion-rusty-bacnet-mcp.md)
5. **External playground** (lessons / vibe labs / DIY router — sibling project) —
   local checkout `~/Desktop/py-bacnet-stacks-playground` or
   [github.com/bbartling/py-bacnet-stacks-playground](https://github.com/bbartling/py-bacnet-stacks-playground)
   - Days 1–27: Python + BACpypes3 / BAC0
   - `vibe_code_apps_13`: DIY BACnet router
   - `vibe_code_apps_16`: Rust BACnet lab
   - Not shipped inside Open-FDD containers

## Quick commands (Mint OptiPlex)

Prefer **fieldbus :8081** Who-Is/read while product owns `:47808`. BACpypes3 only
when fieldbus is stopped — set bind/target from live DHCP (`ip a` / Who-Is JSON),
not baked product defaults.

## MCP sync

BACnet troubleshooting context for hosts is embedded in
[`mcp/INSTRUCTIONS.md`](../../../mcp/INSTRUCTIONS.md) (`include_str!` → GHCR
`openfdd-mcp`). After merge + Publish, refresh the MCP image tag so agents see
Who-Is + ReadProperty + playground pointers. Tools:
`openfdd_bacnet_whois` / `openfdd_bacnet_read` (commission API) and
`openfdd_agent_context_pointers` (doc map).

## Safety

- No BACnet **writes** without explicit human approval.
- Keep rusty-bacnet-mcp **`read_only: true`** unless approved.
- Never print OT credentials or JWTs into public tickets.
