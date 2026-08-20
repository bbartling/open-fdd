# Security policy

## Reporting a vulnerability

Do **not** report security vulnerabilities through public GitHub issues, discussions, Discord, or social-media messages.

Please use GitHub Private Vulnerability Reporting:

https://github.com/bbartling/open-fdd/security/advisories/new

A useful report should include:

- a description of the vulnerability;
- the affected Open-FDD component and version/image tag when known;
- complete reproduction steps;
- proof of impact;
- screenshots or logs with credentials, tokens, private hostnames, and OT details removed;
- a suggested correction, if available.

Private reports are visible only to repository members with the appropriate security permissions and the reporter. Follow-up discussion, evidence, remediation coordination, and an eventual advisory/CVE can stay in the private GitHub security workflow.

If the private reporting form is unavailable to you, contact the maintainer through an existing project contact channel only to request a private reporting path. Do not include vulnerability details or secrets in that initial public message.

## Deployment scope

Open-FDD is currently local-first and intended primarily for LAN/VPN/OT deployments. Railway is an experimental CSV/package lab/demo path, not a claim of production public-internet hardening. Never commit deployment secrets, registry credentials, BAS credentials, JWT secrets, or admin passwords.
