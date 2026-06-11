---
title: Authenticated scanning (roadmap)
parent: Security
nav_order: 4
---

# Authenticated scanning (roadmap)

[ZAP baseline]({% link security/zap-baseline.md %}) is **unauthenticated** — it checks public pages, response headers, and a handful of routes reachable without login. That is the right default for every docker image / patch revision smoke on a test LAN.

For **deep** coverage of integrator dashboards, `/api/*` routes, WebSocket sessions, and role-gated writes, plan a separate **authenticated** scan — only on fake/bench stacks with explicit approval.

Release context: [Security testing cycle]({% link developer/security-testing.md %}).

## Current state (3.0.x)

| Capability | Status |
|------------|--------|
| ZAP baseline via `scripts/security/` | **Shipped** |
| Pentest creds in `workspace/auth.pentest.local` | **Shipped** (host-local, not in git) |
| ZAP full / active scan automation | **Not shipped** — manual only |
| ZAP authenticated context (login script + session) | **Roadmap** |
| CI running ZAP against PR previews | **Not planned** (LAN bench only) |

## Why baseline is not enough

After login, the bridge exposes model editing, BACnet/JSON API configuration, Rule Lab, commissioning export, and write-gated commands. Baseline ZAP never exercises:

- Session cookies / JWT persistence
- CSRF or auth bypass on mutating endpoints
- IDOR on site-scoped resources
- Rate limits and audit logging on failed auth

## Planned approach (contributors welcome)

1. **Bench-only target** — same pentest stack; never point active scans at live OT controllers
2. **Login hook** — ZAP `zap-full-scan.py` or Automation Framework with:
   - `POST /api/auth/login` using integrator creds from env (not committed)
   - Regex or JSON extractor for session token / cookie
3. **Scope file** — include `/api/model/*`, `/api/commissioning/*`, dashboard static assets; exclude BACnet UDP and unrelated LAN hosts
4. **Report parity** — extend `scripts/security/` with opt-in `-Authenticated` / `--zap-full` flags and separate report prefix (`22-zap-authenticated-*`)
5. **Gate** — document accepted findings; fail release only on High/Critical regressions

## Manual authenticated ZAP today

1. Start pentest stack; note creds in `workspace/auth.pentest.local`
2. Open ZAP desktop or docker with API port exposed
3. Configure **Context** → **Authentication** → script or form-based login to `/api/auth/login`
4. Run **Spider** then **Active Scan** on `http://<lan-ip>/` only
5. Compare with baseline report in `openfdd-security-report/`

Do **not** run active scans against production Acme without a maintenance window and BACnet write lock.

## Related

- [scripts/security/README.md](https://github.com/bbartling/open-fdd/blob/master/scripts/security/README.md) — baseline setup
- [Secrets and auth]({% link security/secrets-auth.md %}) — env file layout
- [LAN hardening]({% link security/lan-hardening.md %}) — bind and auth modes
