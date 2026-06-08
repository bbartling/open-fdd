---
title: Deployment modes
parent: Architecture
nav_order: 2
---

# Deployment modes

How Open-FDD is typically run: local development, lab LAN trials, and production edge on a trusted OT/IT network. Open-FDD is designed for **building LAN or OT edge** deployment — not direct exposure to the public internet.

## Mode summary

| Mode | Stack | BACnet | Front door | Auth |
|------|-------|--------|------------|------|
| **Local dev** | Compose on control machine | Optional bench simulator | `127.0.0.1:8765` | `OFDD_AUTH_DISABLED=1` optional on loopback |
| **Lab LAN** | Three GHCR containers | Real or simulator VLAN | Caddy `:80` or direct `:8765` | Required unless explicit insecure lab flags |
| **Edge production** | Three GHCR containers + host Caddy | OT NIC via **commission** | **Caddy** `:80` or `:443` → loopback bridge | **Required** — `workspace/auth.env.local` |

## v3 container stack (all edge modes)

| Image | Role |
|-------|------|
| `openfdd-bridge` | Operator Bridge API, dashboard, **feather historian ingest** |
| `openfdd-commission` | BACnet discover/read/write + **poll loop** |
| `openfdd-mcp-rag` | Doc-search sidecar for agent tools |

{: .note }
> **`openfdd-bacnet-poll` is retired.** BACnet polling runs inside **commission** only. Do not run the legacy poll container or `openfdd-bacnet-poll` systemd unit alongside Docker commission — that double-polls the OT network.

See [Containers](containers) for ports, networks, and persistence.

## Caddy HTTP (typical edge)

- Caddy listens on building LAN `:80`
- Reverse-proxies to bridge at `127.0.0.1:8765`
- Bridge stays loopback-only; operators bookmark `http://<edge-ip>/`

Bootstrap and compose: [Quick Start — Docker](../quick-start/docker).

## Caddy TLS (OT LAN)

For HTTPS on the edge LAN (self-signed or site CA):

1. Generate certs: `./scripts/setup_caddy_certs.sh` (control machine) or site PKI
2. Start with `OFDD_CADDY_MODE=tls`
3. Trust the CA on operator PCs

Details: [TLS and certificates](../security/tls-and-certs). Security headers are set by the **Operator Bridge**; Caddy adds **HSTS** only in TLS mode.

## BACnet data path

```text
OT devices ──UDP 47808──▶ commission (poll loop) ──▶ samples.csv
                                              │
                                              ▼
                                    bridge (ingest) ──▶ feather historian
```

The bridge thread named `bacnet_poll_worker` is **ingest only** — it does not bind BACnet.

## What not to do on production edges

- Port-forward `:8765` to the public internet without TLS and strong auth
- Run `docker compose down -v` or delete `workspace/` on a live site
- Deploy the retired `openfdd-bacnet-poll` image alongside commission

## Related

| Topic | Page |
|-------|------|
| First deploy | [Quick Start — Docker](../quick-start/docker) |
| Upgrade | [Updating the stack](../quick-start/updating) |
| LAN security | [LAN hardening](../security/lan-hardening) |
| Lab example site | [Examples — GL36 lab note](../examples/acme-gl36-lab) |
