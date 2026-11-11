---
title: Security
nav_order: 15
---

# Security

Open-FDD runs inside Normal Framework and uses NF for authentication, point data, and history. It is designed for
trusted building networks and approved remote access. Do not expose an unauthenticated NF console to the public
internet.

## Credentials and access

- Store console credentials and database secrets outside the repository.
- A Normal Online API key can read data but cannot install or deploy the app.
- Use TLS with a trusted certificate for remote access. Do not disable certificate verification.
- The optional Caddy front door can protect console and write routes. Follow the short guidance in
  [Install](install.html) and the repository's deploy/nf-caddy README.
- Open-FDD writes its own result points and weather variables. It does not write to field devices.

## Browser policy and dependencies

The app uses a strict Content Security Policy and serves its UI libraries locally. On the Normal Online portal login
path, the browser loads the pinned Clerk client from the host supplied by the portal identity configuration.
Dependencies are pinned and updated through reviewed changes.

The SPARQL panel and hook reject update operations and remote SERVICE queries, and cap query size and output. CSV
export escapes cells that spreadsheets may interpret as formulas.

## Report a vulnerability

Use GitHub's private vulnerability reporting, not a public issue. See
[SECURITY.md](https://github.com/bbartling/open-fdd/blob/master/SECURITY.md).

CI runs dependency audit, secret scanning, and an OWASP ZAP baseline against the local mock NF server. See
the repository workflow at .github/workflows/security.yml.
