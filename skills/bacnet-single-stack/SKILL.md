---
name: bacnet-single-stack
description: >-
  One BACpypes3/BACnet/IP stack per host on UDP 47808; NIC bind rules, conflict
  detection, Who-Is smoke tests, commission.env. Use when BACnet Who-Is fails,
  port 47808 in use, 127.0.0.1 bind, or multiple BACnet apps on one edge box.
---

# BACnet single-stack exclusivity (Open-FDD edge)

## Rule (non-negotiable on Linux)

**Only one BACnet/IP application may bind UDP port 47808 on a host at a time.**

That includes, in any combination:

| Process | Examples |
|---------|----------|
| Open-FDD | `bacnet_toolshed.commission_agent`, `discover`, `poll_driver` |
| Playground / lab | `mini_weather_device.py`, `mini-schedule-calendar-device.py`, `bacpypes3_version_1.py` |
| Shell / CLI | `python -m bacpypes3 --name … --address …/24 --instance …` |
| Other tools | YABE, Contemporary Controls, DIY BACnet sidecar on 47808 |

The **bridge API (8765)** and **commission HTTP agent (8767)** are separate — they proxy to a single BACpypes3 `Application` inside the commission agent. Starting a second BACpypes3 app on the same NIC/port breaks Who-Is/I-Am for both.

## Bind address (must be NIC IP, not loopback)

BACpypes3 `--address` must be the **host OT/LAN IPv4**, e.g. `192.168.204.18/24:47808` — same pattern as playground apps and [bacpypes3 shell Q&A #125](https://github.com/JoelBender/bacpypes3/discussions/125).

| Bind | Result |
|------|--------|
| `127.0.0.1/24:47808` | Stack starts; **no LAN Who-Is/I-Am** |
| `0.0.0.0/24:47808` | Unreliable on multi-homed hosts; prefer explicit NIC IP |
| `192.168.x.x/24:47808` | Correct for same-subnet field devices |

Open-FDD config: `workspace/bacnet/commissioning/commission.env`

```bash
BACNET_BIND=192.168.204.18/24:47808   # your edge NIC — not 127.0.0.1
BACNET_NAME=OpenFddEdge
BACNET_INSTANCE=599999
```

Auto-resolve: if bind is loopback/empty, `bacnet_toolshed.nic_bind` picks the LAN IP at runtime unless `OFDD_BACNET_BIND_STRICT=1`.

## Agent workflow

1. **Before starting Open-FDD BACnet** — check nothing else holds 47808 (see troubleshooting).
2. **Stop playground simulators** on the edge box when using dashboard Who-Is / commission agent.
3. **After changing `commission.env`** — `./scripts/run_local.sh restart` (commission agent must restart).
4. **Verify with smoke test** before blaming application code:

```bash
./scripts/bacnet_whois_smoke.sh
./scripts/bacnet_whois_smoke.sh --low 3456788 --high 3456799
```

Expected: lines like `3456789 192.168.204.13` (instance + source IP). Exit 1 + “No I-Am” → bind, firewall, range, or **port conflict**.

5. **Do not** start `poll_driver` and commission-agent Who-Is concurrently on the same host without stopping one first.

## Troubleshooting checklist

### 1. Port conflict (most common on dev Pi)

```bash
ss -ulnp | grep 47808
pgrep -af 'bacpypes|commission_agent|mini_weather|mini-schedule|poll_driver|bacnet_toolshed.discover'
```

- If another PID owns 47808 → stop it, then `./scripts/run_local.sh restart`.
- Playground devices in `py-bacnet-stacks-playground/` must be stopped when Open-FDD commission agent runs.

### 2. Wrong bind in commission.env

```bash
grep BACNET_BIND workspace/bacnet/commissioning/commission.env
./scripts/bacnet_whois_smoke.sh --debug
```

Commission agent logs on start: `BACnet stack: name=… bind=192.168.x.x/24:47808`.

### 3. Dashboard Who-Is 500

- Read commission agent response: `curl -s …/api/bacnet/whois` (with auth).
- Past failure: invalid Open-FDD server BACnet objects at stack init (`polarity` on `BinaryValueObject`) — fixed in `bacnet_toolshed/server_points.py`; restart agent after pull.
- “commission agent unreachable” → agent not running on 8767.

### 4. Firewall

UFW may block UDP 47808 from other LAN hosts; localhost smoke can pass while YABE off-box fails. Open OT BACnet UDP if needed.

### 5. Multiple Open-FDD processes

```bash
./scripts/run_local.sh status
./scripts/run_local.sh stop
pkill -f bacnet_toolshed.commission_agent 2>/dev/null || true
./scripts/run_local.sh start
```

## BACpypes3 argv shape (reference)

Commission agent builds the same argv as playground apps:

```text
--name OpenFddEdge --instance 599999 --address 192.168.204.18/24:47808
```

Implementation: `bacnet_toolshed/stack_args.py`, `bacnet_toolshed/nic_bind.py`.

## Related skills

- [driver-bacnet-ingest](../driver-bacnet-ingest/SKILL.md) — discover, poll, CSV
- [local-dev-orchestration](../local-dev-orchestration/SKILL.md) — `run_local.sh`, ports
- [fastapi-bridge-api](../fastapi-bridge-api/SKILL.md) — `/api/bacnet/*` proxy

## Reference

See [references/REFERENCE.md](references/REFERENCE.md) for port map and env vars.
