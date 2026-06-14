---
title: ZAP baseline (local bench)
parent: Security
nav_order: 2
---

# ZAP baseline (local bench)

Passive [OWASP ZAP baseline](https://www.zaproxy.org/docs/docker/baseline-scan/) against the **pentest production stack** on benserver is the standard LAN security smoke before Acme edge deploys.

Full per-revision workflow (pytest → PR → GHCR → Acme): [Developer — security testing cycle]({{ "/developer/security-testing/" | relative_url }}).

Packaged scan scripts (Windows + Mac/Linux): [scripts/security/README.md](https://github.com/bbartling/open-fdd/blob/master/scripts/security/README.md).

## Run

**On the Open-FDD host:**

```bash
./scripts/pentest_production_stack.sh start
./scripts/pentest_production_stack.sh verify
```

**From a LAN workstation** (after verify passes):

```powershell
# Windows — optional integrator auth probe (copy auth.env.local to scan PC; never commit)
.\scripts\security\Run-OpenFddSecurityScan.ps1 -TargetUrl "http://192.168.204.18" `
  -AuthEnvFile "C:\path\to\auth.env.local"
```

The script writes `40-release-gate-summary.txt` with **SECURITY GATE: PASS/FAIL**:
- Fails if production JS bundles contain private LAN IPs or bench Niagara defaults
- Warns if auth env is missing (`Auth loaded: False`) — pass `-AuthEnvFile` or shell vars `OFDD_INTEGRATOR_USER` / `OFDD_INTEGRATOR_PASSWORD` (values are never logged)

```bash
# macOS / Linux
./scripts/security/run_openfdd_security_scan.sh --url http://192.168.204.18
```

ZAP target (example): `http://192.168.204.18/` — Caddy on `:80` only; bridge `:8765` stays loopback. TLS bench: see [TLS and certificates]({{ "/security/tls-and-certs/" | relative_url }}).

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

Baseline scan hits ~4 public endpoints (`/health`, public agent insight routes). Deep API/dashboard coverage requires ZAP with integrator login — see [Authenticated scanning (roadmap)]({{ "/security/authenticated-scanning/" | relative_url }}).

## After fixes

Re-run `pentest_production_stack.sh verify`, then the packaged LAN scan from `scripts/security/`. Confirm response headers show **one** `X-Frame-Options: DENY` and no duplicate `Referrer-Policy`.
