---
title: Security
nav_order: 8
---

# Security

Open-FDD accepts vulnerability reports through **GitHub Private Vulnerability Reporting**.

Do **not** disclose a suspected vulnerability through public GitHub issues, discussions, Discord, or social media.

Use:

**https://github.com/bbartling/open-fdd/security/advisories/new**

Include, when available:

- a description of the vulnerability;
- the affected Open-FDD component and running version/image tag;
- complete reproduction steps;
- proof of impact;
- screenshots or logs with credentials, tokens, private hostnames, and OT details removed;
- a suggested correction.

The private report keeps the finding, discussion, evidence, affected versions, and remediation workflow together in GitHub. Repository maintainers can follow up privately and may publish an advisory or request a CVE after remediation when appropriate.

If the form is unavailable, contact the maintainer only to request a private reporting path; do not send exploit details or secrets through a public channel.

See the repository [`SECURITY.md`](../SECURITY.md) for the canonical reporting policy.

## Deployment posture

Open-FDD remains local-first and LAN/VPN/OT-oriented. The Railway recipe is an experimental CSV/package lab/demo path. Internet-facing deployment requires an independent review of authentication, secrets, TLS, persistence, backups, exposure policy, and network controls.
