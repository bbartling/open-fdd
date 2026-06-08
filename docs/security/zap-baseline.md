---
title: ZAP baseline (local bench)
parent: Security
nav_order: 2
---

# ZAP baseline (local bench)

Passive [OWASP ZAP baseline](https://www.zaproxy.org/docs/docker/baseline-scan/) against the **pentest production stack** on benserver is the standard LAN security smoke before Acme edge deploys.

## Run

```bash
./scripts/pentest_production_stack.sh start
./scripts/pentest_production_stack.sh verify
```

ZAP target (example): `http://192.168.204.18/` — Caddy on `:80` only; bridge `:8765` stays loopback.

## Expected results (HTTP bench mode)

| Finding | Severity | Status |
|---------|----------|--------|
| CSP `style-src 'unsafe-inline'` | Medium | **Accepted** — Vite/React inline styles; TODO to nonce/hash |
| Missing COEP | Low | **Accepted** — `require-corp` not enabled (breaks some assets) |
| Port 80 open (Caddy) | Info | **Expected** — intentional LAN entry |
| Ports 8765, 5173, 8000, 8080 closed | — | **Good** |
| Port 443 filtered | — | **Expected** in HTTP mode; use `OFDD_CADDY_MODE=tls` for HTTPS bench |
| Duplicate `Referrer-Policy` / `X-Frame-Options` | Low | **Fixed** — bridge owns headers; Caddy does not duplicate |

## Header ownership

| Layer | Sets |
|-------|------|
| **Bridge** (`security_headers.py`) | CSP, `X-Frame-Options: DENY`, `frame-ancestors 'none'`, COOP, CORP, Permissions-Policy, Referrer-Policy, `X-Content-Type-Options` |
| **Caddy HTTP** | Reverse proxy only; strips `Server` banners |
| **Caddy TLS** | Adds `Strict-Transport-Security` only |

## Authenticated scan (later)

Baseline scan hits ~4 public endpoints (`/health`, public agent insight routes). Deep API/dashboard coverage requires ZAP with integrator login — schedule separately before production OT LAN sign-off.

## After fixes

Re-run verify, then remote PowerShell ZAP from the LAN PC. Confirm response headers show **one** `X-Frame-Options: DENY` and no duplicate `Referrer-Policy`.
