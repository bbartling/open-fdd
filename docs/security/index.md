---
title: Security
nav_order: 9
has_children: true
---

# Security

LAN deployment security for the Operator Bridge and BACnet write guard. Open-FDD is for **trusted edge / OT LAN** — not direct public internet exposure.

| Page | Topic |
|------|-------|
| [LAN hardening]({% link security/lan-hardening.md %}) | Auth and bind modes |
| [ZAP baseline (local bench)]({% link security/zap-baseline.md %}) | Pentest stack, expected warnings |
| [TLS and certificates]({% link security/tls-and-certs.md %}) | Cert ownership, bench TLS mode |
| [Linux host hardening]({% link security/linux-host-hardening.md %}) | Ubuntu edge VM, SSH, kernel, Ollama bind |
| [Tenable / Nessus remediation]({% link security/tenable-remediation.md %}) | IT scan findings, operator runbook |
| [Authenticated scanning (roadmap)]({% link security/authenticated-scanning.md %}) | Deep ZAP / protected API |
| [Secrets and auth]({% link security/secrets-auth.md %}) | Env files |
| [BACnet write allowlists]({% link security/bacnet-writes.md %}) | Supervisory write gates |
| [Release & LAN scan cycle]({% link developer/security-testing.md %}) | Per-revision ZAP + CI workflow |
| [Logging and audit]({% link ops/logging.md %}) | Auth audit trail, rotation, SIEM |
