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
wire-level BACnet. Product poll stays on **`openfdd-fieldbus`**. Use this skill
when discovery or sensor reads fail.

## Always prove both layers

| Layer | Must pass | Why |
|-------|-----------|-----|
| **Who-Is** | ≥1 I-Am on the OT NIC | BVLL bound; peers reachable |
| **ReadProperty** | Numeric `present-value` on a known object | IPs change; discovery alone is not enough |

Peer addresses on the Mint bench (**`192.168.204.0/24`**) move with DHCP — set
`READ_TARGET` / `--target` when the sim/device IP changes.

## Where to look (in order)

1. **Local Mint BACpypes3 bench** (this repo)
   - Doc: [`docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md`](../../../docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md)
   - Script: `./scripts/ops/local_bacnet_ot_bench.sh sensor`
   - Python: `scripts/ops/bacpypes3_whois_smoke.py` (`whois` | `read` | `sensor`)
2. **Product fieldbus** — `POST http://127.0.0.1:8081/bacnet/whois` and read APIs;
   Who-Is binds `0.0.0.0` + hosted port (`SO_REUSEADDR`, #526). Unicast reads use
   ephemeral ports. Poll is **hard-coded 300 s** — never put fieldbus on Railway.
   Policy: [`docs/operations/BACNET_OT_POLICY.md`](../../../docs/operations/BACNET_OT_POLICY.md)
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

```bash
# Prefer sensor (Who-Is + read). Override target when DHCP moves the peer.
READ_TARGET=192.168.204.55 READ_OBJECT=analog-value,1 EXPECT_MIN=0 EXPECT_MAX=200 \
  ./scripts/ops/local_bacnet_ot_bench.sh sensor

.venv-bacpypes3/bin/python scripts/ops/bacpypes3_whois_smoke.py read \
  --address 192.168.204.11/24 --target 192.168.204.55 \
  --object analog-value,1 --property present-value
```

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
