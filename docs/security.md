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

- **Strict CSP, with one exception**: pages ship with `default-src 'self'` and no inline scripts or styles, and
  `wasm-unsafe-eval` for the WASM engines (SPARQL panel). ECharts and every other library are vendored and served
  from the app itself. The exception is the Normal Online (portal) login: when NF reports the Clerk identity
  provider, `nf.js` loads `clerk-js` at an exact pinned version (`CLERK_JS_VERSION`, currently 5.128.1) from the
  host named in the portal's publishable key (a Clerk frontend API host). That host is only known at runtime, so
  the CSP cannot name it and keeps `script-src 'self' https:` and `connect-src 'self' https:`: any https script
  source is *permitted* by the policy, and only the pinned Clerk script is *loaded* by the code. On the LAN path
  (no Clerk) nothing is loaded from outside. Residual risk: the Clerk file is trusted by version, not by
  Subresource Integrity hash, and the broad `https:` allowance would not stop a script injected some other way.
  This is a known limit, not a "self-only" policy.
- **SPARQL is read-only**: the panel and the `sparql` hook run only SELECT, ASK, CONSTRUCT and DESCRIBE; UPDATE
  operations and `SERVICE` (remote federation) are refused before the engine sees the query; the query text is
  capped at 20000 characters and the returned rows at 5000. The hook refuses a model over a triple limit (default
  500000, env `OPENFDD_SPARQL_MAX_TRIPLES`, a caller can only lower it) before evaluating. A single Oxigraph (wasm)
  evaluation cannot be interrupted from the thread it runs on: the browser panel therefore runs queries in a Web
  Worker and terminates it after 20 s; the hook has no such timeout (NF's hook `invokeTimeout` bounds how long
  the run is waited for, not necessarily the CPU work), so keep hook queries selective.
- **CSV export**: text cells that a spreadsheet would read as a formula (start with `=`, `+`, `-`, `@`, tab or
  CR, also after leading spaces) are prefixed with `'`; numbers stay numbers.
- **No blind retries**: `nf.js` retries transient errors only for reads (GET, `point/query`, `auth/token`).
  StartHook and every other POST/PATCH/DELETE is sent once, so a lost response can never start a second run.
- **No credentials in the app**: auth is NF's. On the LAN the app logs in to NF; through the portal it sends the
  console's own bearer token.
- **Front door**: the optional Caddy proxy keeps the console and every write behind basic auth
  ([Install](install.html)). Plain HTTP is for a trusted LAN or lab only (the password is not encrypted); HTTPS
  (`Caddyfile.tls`) is the production profile. The dashboard and its read-only API calls are open by design
  (an explicit public-read choice, listed with the way to lock them in `deploy/nf-caddy/README.md`). It keeps a
  bounded JSON access log with Authorization, Cookie and token query parameters redacted.
- **Read-mostly**: the app writes only its own FDD result points and weather variables. It never writes to field
  devices.
- **Supply chain**: dependencies are pinned in `package-lock.json`; releases younger than two weeks are not taken.
