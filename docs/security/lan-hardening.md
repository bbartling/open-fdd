---
title: LAN hardening
parent: Security
nav_order: 1
---

# LAN hardening

Open-FDD targets **trusted building LAN / OT edge** deployment. The Operator Bridge is not intended for direct public internet exposure.

Full mode matrix: [Deployment modes](../architecture/deployment-modes).

## Auth and bind

| Mode | Bridge bind | Auth |
|------|-------------|------|
| Local dev | `127.0.0.1` | Optional `OFDD_AUTH_DISABLED=1` on loopback |
| Lab LAN | `0.0.0.0` | Required unless explicit insecure lab flags |
| Edge production | Loopback + **Caddy** on LAN | **Required** — `OFDD_AUTH_SECRET` + role passwords |

Startup **fails** on non-loopback bind without credentials (unless insecure lab flags are set).

## Network exposure

- Put **Caddy** on `:80` / `:443`; keep bridge `:8765` on loopback when possible.
- Do not port-forward the Operator Bridge to the public internet without TLS and strong auth.
- Keep BACnet on OT VLANs; management UI on IT VLAN with firewall rules.
- BACnet **writes** are gated by default — [BACnet write guard](bacnet-writes).

## Rule Lab

Rule Lab runs **operator-authored Python** in a sandbox. Restrict integrator accounts; review rules before enable on production sites.

## TLS and LAN security scans

| Topic | Page |
|-------|------|
| Certificates (self-signed / site CA) | [TLS and certificates](tls-and-certs) |
| ZAP + Nmap bench smoke | [ZAP baseline](zap-baseline) · `scripts/security/` |
| Ubuntu host + Tenable/Nessus | [Linux host hardening](linux-host-hardening) · [Tenable remediation](tenable-remediation) |
| Release test cycle (maintainers) | [Security testing](../developer/security-testing) |

## Ollama on the edge

Ollama has **no built-in auth**. Bind `OLLAMA_HOST=127.0.0.1:11434` on the host; never expose `:11434` on the OT LAN. Open-FDD bridge reaches Ollama server-side only. Validation: `scripts/security/check_openfdd_exposure.sh`.
