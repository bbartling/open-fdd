---
title: Security
nav_order: 12
---

# Security

Open-FDD is intended for LAN, VPN and OT deployments behind Normal Framework. It makes no claim of
public-internet hardening. Never commit secrets (NF console passwords, API keys, BAS credentials).

## Reporting a vulnerability

Use GitHub Private Vulnerability Reporting, not public issues or chat. See
[SECURITY.md](https://github.com/bbartling/open-fdd/blob/master/SECURITY.md).

## What CI checks

The `Security` workflow (`.github/workflows/security.yml`) runs on every push and pull request, and weekly:

| Check | What |
|---|---|
| **ZAP baseline** | OWASP ZAP baseline scan against the running mock NF (`node nf-app/dev/mock-nf.mjs`), serving the real app pages; the report is kept as a build artifact |
| **npm audit** | `npm audit --audit-level=high` on `nf-app/` dependencies |
| **gitleaks** | secret scan over the commit range (allowlist in `.gitleaks.toml`) |

## Design rules

- **Strict CSP**: pages ship with `default-src 'self'` and no inline scripts or styles. Only `wasm-unsafe-eval` is
  allowed, for the WASM SQL engines (SPARQL panel). ECharts and every library are vendored; no CDN at runtime
  (the Normal Online login loads clerk-js only when NF reports Clerk).
- **No credentials in the app**: auth is NF's. On the LAN the app logs in to NF; through the portal it sends the
  console's own bearer token.
- **Front door**: the optional Caddy proxy keeps the console and every write behind basic auth
  ([Install](install.html)).
- **Read-mostly**: the app writes only its own FDD result points and weather variables. It never writes to field
  devices.
- **Supply chain**: dependencies are pinned in `package-lock.json`; releases younger than two weeks are not taken.
