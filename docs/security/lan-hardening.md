---
title: LAN hardening
parent: Security
nav_order: 1
---

# LAN hardening

## Deployment modes

| Mode | Bind | Auth |
|------|------|------|
| Local dev | `127.0.0.1` | Optional `OFDD_AUTH_DISABLED=1` |
| Lab LAN (insecure) | `0.0.0.0` | Requires explicit insecure dev flags — **not production** |
| Edge production | `0.0.0.0` behind Caddy | **Required** credentials + `OFDD_AUTH_SECRET` |

Startup **fails** on non-loopback bind without credentials (unless insecure lab flags are explicitly set).

## Network exposure

- Do not port-forward the bridge to the public internet without TLS and strong auth.
- Keep BACnet on OT VLANs; bridge management on IT VLAN with firewall rules.
- Prefer Caddy on `:80`/`443` rather than exposing `:8765` directly.

## Rule Lab caution

Rule Lab executes **operator-authored Python** in a sandbox. Restrict integrator accounts; review rules before enable on production sites.

## TLS and scanning

- Certificate generation and renewal: [TLS and certificates](tls-and-certs)
- Per-revision ZAP + Nmap from a LAN PC: [Security testing cycle](../developer/security-testing) and [ZAP baseline](zap-baseline)
