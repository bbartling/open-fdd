# Security policy

## Reporting a vulnerability

Do **not** report security vulnerabilities through public GitHub issues, discussions, Discord, or social-media messages.

Please use GitHub Private Vulnerability Reporting:

https://github.com/bbartling/open-fdd/security/advisories/new

A useful report should include:

- a description of the vulnerability;
- the affected component (`nf-app`, `lite`, a hook, the Caddy front door) and the Open-FDD version;
- complete reproduction steps;
- proof of impact;
- screenshots or logs with credentials, tokens, private hostnames, and OT details removed;
- a suggested correction, if available.

Private reports are visible only to repository members with the appropriate security permissions and the reporter. Follow-up discussion, evidence, remediation coordination, and an eventual advisory/CVE can stay in the private GitHub security workflow.

If the private reporting form is unavailable to you, contact the maintainer through an existing project contact channel only to request a private reporting path. Do not include vulnerability details or secrets in that initial public message.

## Deployment scope

Open-FDD 5.0 is a Normal Framework (NF) app intended for LAN, VPN and OT deployments behind NF (authentication, remote
access and the console are NF's). It makes no claim of production public-internet hardening. The optional Caddy front
door (`deploy/nf-caddy`) keeps the console and writes behind a login; its plain-HTTP profile is for a trusted LAN or
lab only (HTTPS is the production profile), and the dashboard's read-only routes are open by design unless you lock
them (see its README). The pages are self-hosted except for one runtime script: on the portal (Normal Online) path the
login loads `clerk-js`, at a pinned exact version, from the Clerk host in the portal's publishable key, so the page CSP
allows `https:` scripts rather than only `'self'`. CI runs ZAP against the mock NF, `npm audit` and
gitleaks; see the [security docs](docs/security.md). Never commit NF passwords, API keys, tokens, certificates or BAS credentials.
