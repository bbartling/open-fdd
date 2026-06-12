---
title: Security
nav_order: 9
has_children: true
---

# Security

LAN deployment security for the Operator Bridge and BACnet write guard. Open-FDD is for **trusted edge / OT LAN** — not direct public internet exposure.

| Page | Topic |
|------|-------|
| [LAN hardening]({{ "/security/lan-hardening/" | relative_url }}) | Auth and bind modes |
| [ZAP baseline (local bench)]({{ "/security/zap-baseline/" | relative_url }}) | Pentest stack, expected warnings |
| [TLS and certificates]({{ "/security/tls-and-certs/" | relative_url }}) | Cert ownership, bench TLS mode |
| [Linux host hardening]({{ "/security/linux-host-hardening/" | relative_url }}) | Ubuntu edge VM, SSH, kernel, Ollama bind |
| [Tenable / Nessus remediation]({{ "/security/tenable-remediation/" | relative_url }}) | IT scan findings, operator runbook |
| [Authenticated scanning (roadmap)]({{ "/security/authenticated-scanning/" | relative_url }}) | Deep ZAP / protected API |
| [Secrets and auth]({{ "/security/secrets-auth/" | relative_url }}) | Env files |
| [BACnet write allowlists]({{ "/security/bacnet-writes/" | relative_url }}) | Supervisory write gates |
| [Release & LAN scan cycle]({{ "/developer/security-testing/" | relative_url }}) | Per-revision ZAP + CI workflow |
| [Logging and audit]({{ "/ops/logging/" | relative_url }}) | Auth audit trail, rotation, SIEM |
