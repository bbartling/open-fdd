# Open-FDD OS — concept (Home Assistant OS–inspired)

**Future concept only.** Open-FDD **3.2.x** ships as Docker on a generic Linux host. This document captures design intent for a dedicated appliance OS — analogous to how [Home Assistant OS](https://developers.home-assistant.io/docs/operating-system/) wraps Home Assistant Core.

## Why an appliance OS?

Building FDD edges run headless for years on LANs with:

- BACnet / Modbus on local NICs (host networking, multicast)
- Large historian partitions on durable storage
- Infrequent, trusted operator updates (integrator/agent JWT)
- Need for rollback when an OTA bundle misbehaves

A **single-purpose OS image** reduces drift (no desktop packages, no accidental `apt upgrade` breaking Docker), simplifies field support, and enables signed OTA — the same reasons Home Assistant moved from “Docker on Raspbian” to **HA OS**.

## Design principles (aligned with HA OS, adapted for FDD)

| Principle | Open-FDD interpretation |
| --- | --- |
| **Appliance, not desktop** | No GUI desktop; SSH optional; dashboard via browser to bridge `:8080` or Caddy |
| **Read-only root** | OS rootfs immutable; all site state in `/var/openfdd/workspace` |
| **Containers only** | Rust edge runs in GHCR containers — never `cargo install` on host for production |
| **Supervisor layer** | Future daemon or script bundle: compose up, health, pinned versions, addon profiles (`mcp-sidecar`, `caddy-tls`) |
| **OTA with rollback** | RAUC A/B slots for OS; separate channel for “supervisor + app” bundle (compose + manifest) |
| **Board support packages** | x86_64 UEFI (Acme VM, NUC-class), Raspberry Pi 4/5 ARM64 |
| **LAN-first security** | Bind API to loopback or site VLAN; JWT auth; no public internet exposure by default |

## Mapping: Home Assistant → Open-FDD

| Home Assistant | Open-FDD (planned) |
| --- | --- |
| HA OS | Open-FDD OS (`os/`) |
| Supervisor | Future supervisor (compose + manifest; today: `scripts/openfdd_rust_*`) |
| Home Assistant Core | `openfdd-bridge` container (`open_fdd_edge_prototype`) |
| Add-ons | GHCR sidecars: commission, haystack-gateway, `openfdd-mcp`, Caddy |
| `/config` | `workspace/` (historian, Haystack grid, rules, auth) |
| Home Assistant Container | **Not the goal** — we target appliance OS, not “Docker on random Linux” long term |

## Rust cargo project (not Python)

Legacy Open-FDD docs referenced Python sidecars and `mcp-rag`. The **3.2 Rust edge** baseline is:

```text
Cargo workspace
├── edge/     → open_fdd_edge_prototype (bridge, commission modes)
└── mcp/      → openfdd-mcp (optional MCP stdio sidecar)
```

The OS image would ship **Docker + RAUC + kernel** only. Application bytes come from GHCR builds of those crates — same as today, but with a controlled host and OTA path.

## Non-goals (for Open-FDD OS)

- Running application code via `pip`, `npm`, or host `cargo run` in production
- Multi-tenant unrelated stacks on one edge (single `openfdd-edge` compose project)
- Cloud-dependent runtime (must operate offline on building LAN)
- Embedding Ollama or MCP **inside** the bridge container (optional sidecars only)
- Replacing integrator workflow before Phase A (Ubuntu + GHCR) is stable on field Pi

## Relationship to current deploys

**Phase A (now):** Ubuntu 24.04 or Raspberry Pi OS + Docker CE + the compose recipes in [`docker/`](../../docker/) via [`scripts/openfdd_stack_up.sh`](../../scripts/openfdd_stack_up.sh).

**Phase D (future):** Flash Open-FDD OS image → supervisor pulls pinned GHCR tags → OTA updates OS and app bundle.

No code in `os/` is required to install, update, or validate a site in 3.2.x.
