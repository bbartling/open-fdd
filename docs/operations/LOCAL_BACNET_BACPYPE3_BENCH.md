---
title: Local BACnet + BACpypes3 bench (Mint)
parent: Operations
nav_order: 19
---

# Local BACnet / BACpypes3 OT bench (Mint OptiPlex)

Use this host to troubleshoot **BACnet → fieldbus → MQTTS → central** without Railway
or ACME VIM.

**Production path:** `openfdd-fieldbus` + **rusty-bacnet** (Rust). Poll/publish stays
fixed **300 s**. Never put fieldbus on Railway.

**BACpypes3 / Python:** diagnose-only (Who-Is / ReadProperty when you need a second
stack). Not a product driver; exit or `pkill` before fieldbus owns UDP **47808**.

**Typical Mint NIC:** `eno1` → `192.168.204.11/24` (confirm with `ip a`; private bench
IP — keep out of product code).

## Critical: one listener on UDP 47808

Linux (and BACnet/IP) effectively allow **one** process to own the hosted BACnet/IP port (**UDP 47808**). A lingering **BACpypes3** shell / Who-Is smoke **and** `openfdd-fieldbus` cannot both bind that port.

**Before** `./scripts/openfdd_stack_up.sh react-ot` (or any fieldbus that hosts `:47808`):

```bash
# Preferred preflight (kills whatever holds 47808/udp)
./scripts/fieldbus/preflight_free_47808.sh

# Or explicitly stop interactive BACpypes3 / smoke leftovers
pkill -f 'python -m bacpypes3' 2>/dev/null || true
pkill -f bacpypes3_whois_smoke 2>/dev/null || true
ss -ulnp | grep 47808 || echo "OK: UDP 47808 free"
```

After fieldbus is up, do **host** Who-Is/reads from BACpypes3 only if you stop fieldbus first — or use fieldbus `:8081` / rusty-bacnet-mcp for wire checks while the product owns 47808.

## Three proofs (LAN)

| Layer | What it proves | Tool |
|-------|----------------|------|
| **A. Who-Is** | OT LAN hears I-Am | BACpypes3 on the host NIC |
| **A2. ReadProperty / sensor** | Unicast read of a known object (IPs change on the bench) | same script: `read` / `sensor` |
| **B. MQTTS pipeline** | Product containers ingest BACnet telemetry over MQTTS | GHCR `sha-*` + `bacnet_mqtt_container_smoke.sh` |

Who-Is alone is **not** enough — DHCP moves peers (`.12` / `.55` / …). Always follow with a **sensor** ReadProperty (numeric `present-value`, optional range).

Layer B uses an **isolated docker network** + containerized BACpypes3 simulator (Optional BACnet CI). It does **not** require live MS/TP and does not fight the host for 47808.

## One-shot script

```bash
cd ~/Desktop/open-fdd   # or your checkout

# First time: script bootstraps .venv-bacpypes3 via uv (no apt/sudo)
./scripts/ops/local_bacnet_ot_bench.sh              # sensor + pipeline
./scripts/ops/local_bacnet_ot_bench.sh whois          # discovery only
./scripts/ops/local_bacnet_ot_bench.sh sensor         # Who-Is + ReadProperty
READ_TARGET=192.168.204.55 READ_OBJECT=analog-value,1 \
  EXPECT_MIN=0 EXPECT_MAX=200 \
  ./scripts/ops/local_bacnet_ot_bench.sh sensor
READ_TARGET=192.168.204.55 ./scripts/ops/local_bacnet_ot_bench.sh read
OPENFDD_IMAGE_TAG=sha-9072e0b \
  ./scripts/ops/local_bacnet_ot_bench.sh pipeline     # containers only
```

Bind override: `BIND=192.168.204.11/24 ./scripts/ops/local_bacnet_ot_bench.sh sensor`

Artifacts land under `reports/local_bacnet_ot_<UTC>/`.

## Manual BACpypes3 shell (same as Joel Bender discussion)

Upstream Q&A + Ben’s Pi example: [BACpypes3 discussion #125](https://github.com/JoelBender/BACpypes3/discussions/125#discussioncomment-16177547).

```bash
# venv (uv recommended on Mint without python3-venv apt)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
cd ~/Desktop/open-fdd
uv venv .venv-bacpypes3
uv pip install --python .venv-bacpypes3/bin/python bacpypes3 ifaddr
source .venv-bacpypes3/bin/activate

# Interactive shell — bind THIS host’s OT address/prefix
# Reminder: exit this shell (or pkill) before openfdd-fieldbus owns :47808
python -m bacpypes3 \
  --name MintWhoIsTest \
  --address 192.168.204.11/24 \
  --instance 59999 \
  --debug

> whois
# Expect I-Am lines from peers (e.g. bosspi / fake devices on .12–.55)
> whois 1000 3456799
> read 192.168.204.55 analog-value,1 present-value
```

**Cause of “YABE sees nothing until I run whois”:** the mini-device shell often answers Who-Is only after the application is fully up; issuing `whois` / `iam` in-shell confirms BVLL is bound. Prefer binding the **real DHCP address/prefix** (e.g. `192.168.204.11/24`), not a link-local `/16`, unless that is truly your OT segment.

Non-interactive:

```bash
.venv-bacpypes3/bin/python scripts/ops/bacpypes3_whois_smoke.py whois \
  --address 192.168.204.11/24 --timeout 8 --json

.venv-bacpypes3/bin/python scripts/ops/bacpypes3_whois_smoke.py read \
  --address 192.168.204.11/24 --target 192.168.204.55 \
  --object analog-value,1 --property present-value

.venv-bacpypes3/bin/python scripts/ops/bacpypes3_whois_smoke.py sensor \
  --address 192.168.204.11/24 --target 192.168.204.55 \
  --object analog-value,1 --expect-min 0 --expect-max 200 --json
```

## MQTTS pipeline (Open-FDD containers)

```bash
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-mqtt openfdd-fieldbus
OPENFDD_IMAGE_TAG=sha-<7> ./scripts/integration/bacnet_mqtt_container_smoke.sh
# or:
OPENFDD_IMAGE_TAG=sha-<7> ./scripts/ops/local_bacnet_ot_bench.sh pipeline
```

Compose: `docker/compose.bacnet-mqtt-ci.yml` — sim → fieldbus → mqtt → central.

### Full product stack on LAN (optional)

```bash
./scripts/fieldbus/preflight_free_47808.sh   # kill BACpypes3 / free :47808 first
export OPENFDD_IMAGE_TAG=sha-<7>
export OPENFDD_FIELDBUS_BIND=192.168.204.11
./scripts/openfdd_stack_up.sh react-ot
# Then browse UI :3000; fieldbus Who-Is: POST http://127.0.0.1:8081/bacnet/whois
```

Keep poll **300 s** (compiled). Do not put fieldbus on Railway.

This Mint host may need a **user-local** Docker Compose v2 plugin (`~/.docker/cli-plugins/docker-compose`) if `apt` does not provide `docker compose`.

## Troubleshooting map

| Need | Where |
|------|--------|
| Policy / 300 s poll | [`BACNET_OT_POLICY.md`](BACNET_OT_POLICY.md) |
| Edge → cloud MQTTS hub | [`FIELDBUS_EDGE_MQTTS_HUB.md`](FIELDBUS_EDGE_MQTTS_HUB.md) |
| Agent skill | [`openfdd-bacnet-ot-debug`](../../openfdd_agent_spec/skills/openfdd-bacnet-ot-debug/SKILL.md) |
| MCP instructions (GHCR `openfdd-mcp`) | [`mcp/INSTRUCTIONS.md`](../../mcp/INSTRUCTIONS.md) |
| Companion wire MCP | [`../mcp-agents/companion-rusty-bacnet-mcp.md`](../mcp-agents/companion-rusty-bacnet-mcp.md) |
| Lessons / DIY router / rusty labs (sibling) | [`~/Desktop/py-bacnet-stacks-playground`](https://github.com/bbartling/py-bacnet-stacks-playground) |
| Free `:47808` | `scripts/fieldbus/preflight_free_47808.sh` |
| Upstream shell tip | [BACpypes3 discussion #125](https://github.com/JoelBender/BACpypes3/discussions/125#discussioncomment-16177547) |
