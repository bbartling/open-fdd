# Open-FDD OS (future concept)

> **Status:** Design placeholder only — **not** used for production deploys in Open-FDD **3.2.x**.  
> Inspired by [Home Assistant OS](https://www.home-assistant.io/operating-system/) (dedicated appliance image, read-only root, container runtime, OTA updates). Open-FDD OS would apply the same *shape* to **HVAC edge FDD** on BACnet/Modbus/Haystack building networks.

## What this is

A **future** thin Linux host image for field edge devices:

- Read-only root filesystem (SquashFS or equivalent)
- Container engine as the **only** application runtime
- Writable state on a dedicated partition (`/var/openfdd` → bind-mount `workspace/`)
- A/B OTA updates (RAUC or similar) for OS + supervisor bundle
- Board support: x86_64 UEFI (VM/bench), Raspberry Pi 4/5 (ARM64 field Pi)

**Application logic stays in published GHCR images**, compiled from the Rust workspace (`services/`, `mcp/`) — not baked into the OS rootfs.

## What this is not (today)

| Do not use `os/` for | Use instead |
| --- | --- |
| Fresh site install | [`scripts/openfdd_stack_up.sh`](../scripts/openfdd_stack_up.sh) |
| Image updates | [`scripts/openfdd_stack_up.sh`](../scripts/openfdd_stack_up.sh) + GHCR |
| Compose stack | [`docker/compose.standalone.yml`](../docker/compose.standalone.yml) (+ central/edge/csv recipes) |
| Optional MCP server | [`mcp/README.md`](../mcp/README.md) |

Current production path: **Ubuntu (or Pi OS) + Docker CE + the GHCR container stack** — same operational model Home Assistant used before HA OS matured, but with Open-FDD’s Rust cargo crates under the hood.

## Layered model (HA OS–like)

```text
┌─────────────────────────────────────────────────────────────┐
│  Open-FDD OS (future) — Buildroot / board image              │
│  Kernel · read-only root · Docker · RAUC A/B (planned)       │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  Supervisor (future) — compose project + version manifest    │
│  Pins GHCR tags · health · rollback · addon profiles           │
└───────────────────────────┬─────────────────────────────────┘
                            │
    ┌──────────┬───────────┼───────────┬──────────┐
    ▼          ▼           ▼           ▼          
  central      ui       fieldbus     mqtt
  (API/FDD)  (Caddy)   (BACnet→MQTTS) (broker)
    │          │           │           │
    └──────────┴───────────┴───────────┘
                            │
                    workspace/ (persistent)
                    historian · Haystack model · rules · auth
```

Optional addon (separate GHCR image, stdio MCP):

```text
  openfdd-mcp  ←  cargo crate `openfdd-mcp`, talks to central
```

## Repo layout (concept vs implemented)

| Path | Role | 3.2.x today |
| --- | --- | --- |
| `os/` | Board defs, Buildroot external, OTA bundles | **This folder — docs only** |
| `services/` | Rust central/fieldbus/mqtt + UI build | **Implemented** |
| `mcp/` | Read-first MCP stdio server (`openfdd-mcp`) | **Scaffold + GHCR** |
| `docker/` | compose recipes (standalone/central/edge/csv) | **Implemented** |
| `workspace/` | Site state (bind-mounted) | **Implemented** |
| `scripts/` | Bootstrap, backup, update, validate | **Implemented** |

There is **no** `supervisor/` crate yet; today Compose + lifecycle scripts play that role.

## Rust under the hood

Open-FDD OS would **not** ship Python or `pip install` on the host. Containers are built from:

| Crate / package | GHCR image | Role |
| --- | --- | --- |
| `openfdd-central` | `ghcr.io/bbartling/openfdd-central` | API + FDD engine |
| UI (Vite → Caddy) | `ghcr.io/bbartling/openfdd-ui` | static dashboard |
| `openfdd-fieldbus` | `ghcr.io/bbartling/openfdd-fieldbus` | BACnet → MQTTS |
| `openfdd-mqtt` | `ghcr.io/bbartling/openfdd-mqtt` | Mosquitto broker |
| `openfdd-mcp` | `ghcr.io/bbartling/openfdd-mcp` | stdio MCP |

CI: [`.github/workflows/ghcr-openfdd-stack.yml`](../.github/workflows/ghcr-openfdd-stack.yml), [`.github/workflows/rust-ghcr-mcp.yml`](../.github/workflows/rust-ghcr-mcp.yml).

## Documentation

| Doc | Purpose |
| --- | --- |
| [Documentation/concept.md](Documentation/concept.md) | Home Assistant OS inspiration, principles, non-goals |
| [Documentation/roadmap.md](Documentation/roadmap.md) | Phased delivery (A → D) |

## Development today

Use a normal Linux edge host (WSL bench, VM, Raspberry Pi) with Docker and the GHCR container stack. Do **not** block releases on `os/` image work.

Quick start: [docs/quick-start/docker-ghcr.md](../docs/quick-start/docker-ghcr.md).
