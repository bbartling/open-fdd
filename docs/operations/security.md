---
title: Security
parent: Operations
nav_order: 11
nav_exclude: true

---

# Security

## Deployment posture

Open-FDD is **local-first** for LAN, VPN, or OT networks. Central binds the API on **:8080** and the `openfdd-web` React container serves the engineering UI on **:3000**.

{: .warning }
Open-FDD is **not internet-ready**. LAN / VPN / OT only until the checklist below is complete **and** independently reviewed.

## Not internet-ready until

- [x] Fail-closed when Central binds non-loopback without a ≥32-char `OPENFDD_JWT_SECRET` and `OPENFDD_ADMIN_PASSWORD`
- [x] Open mode (unset JWT secret) is loopback-only
- [x] Startup logs `auth_enabled` **without** secrets
- [ ] Dedicated reverse proxy / TLS on every deployment (expose **web proxy only**; do not publish `:8080` to the internet)
- [x] Multi-tenant building ACL when `OPENFDD_MULTI_TENANT=1` (`TenantContext::allow_building` on data paths; `/api/tenants` JWT-only — Kali O2c)
- [x] Viewer is read-only; mutations require operator/admin
- [x] Login throttle + generic credential errors
- [x] Package zip-slip / bomb caps on archive ingest
- [x] No wildcard CORS in the SPA nginx config
- [x] SPA CSP without `unsafe-eval` (Unity `/twins` may use `wasm-unsafe-eval` only); Google Fonts allowlisted; HSTS when `X-Forwarded-Proto=https`
- [x] `/.well-known/security.txt` served as text/plain (not SPA HTML)
- [ ] Production secret rotation, SSO, and WAF as required by the site
- [ ] Staging MQTT ACL pairwise deny proof (Kali)

OT writes stay **off** unless an operator explicitly enables them.

## Deployment posture

## Caddy edge (optional)

Optional compose overlay `docker/compose.caddy.react.yml` puts **Caddy on :80** so
`http://<machine-ip>/` serves the React SPA (and `/api*` → central). Enable with
react / react-ot / csv recipes (default ON for react/react-ot):

```bash
OPENFDD_CADDY=1 ./scripts/openfdd_stack_up.sh react
# or: docker compose -f docker/compose.react.yml -f docker/compose.caddy.react.yml up -d
```

Security defaults in the Caddyfiles: admin API off, security headers, probe-path
404s, `no-new-privileges`, dropped capabilities. When Caddy fronts the LAN, bind
central to loopback: `OPENFDD_CENTRAL_BIND=127.0.0.1`. Use a TLS Caddyfile (+ certs)
for HTTPS / HSTS when you terminate TLS at the edge.

## Authentication

- JWT on protected REST routes
- Credentials in `workspace/auth.env.local` (mode `600`, never commit)
- Integrator role for commissioning; rotate with `openfdd_auth_init.sh`
- **Kali O2c / Wave P2c:** With auth ON, `/api/tenants`, `/api/capabilities`, `/api/health/stack`, `/api/building/snapshot`, and `/api/dashboard/summary` require Bearer JWT (401 unauth). Never Admin-via-`dev_anonymous` for those handlers. Public readiness = `GET /api/health`. Regression: `cargo test -p openfdd-central --test preauth_disclosure`. Agent skill: `openfdd_agent_spec/skills/openfdd-mt-security`.

## TLS

The `openfdd-web` React app talks to central’s REST API (`:8080`). For HTTPS
on the LAN edge, use the Caddy TLS Caddyfile (above) or terminate TLS on your
ingress. MQTT between fieldbus edges and central is always MQTTS (8883) using
the per-site provisioning kits.

## Secrets

- Never log or commit tokens, passwords, or `auth.env.local`
- MCP agents receive JWT via environment — not embedded in docs

## Audit and application logging (pen-test ready)

Industry-typical dual sink — enough for auditors / pen testers, not a SIEM product:

| Channel | What | Where |
|---------|------|--------|
| **Security audit** | Login success/fail/throttle, command authz, command issue, telemetry suspend/resume, fieldbus API-key rejects | JSONL file + stdout target `security_audit` |
| **App / error logs** | `tracing` at info/warn/error with `request_id` | stdout (Railway / AWS / `docker logs`) |

**File audit (local + volume mounts):**

```text
$OPENFDD_WORKSPACE/logs/security_audit.jsonl
# also mirrored to auth_audit.jsonl for older tooling
```

Rotation (defaults): `OPENFDD_AUDIT_LOG_MAX_BYTES=10485760` (10 MiB), `OPENFDD_AUDIT_LOG_KEEP=5`.
Override path with `OPENFDD_AUDIT_LOG_PATH`. Secrets / passwords / tokens / API keys are redacted.

**Container stdout rotation (GHCR compose / local Docker):**

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"
```

**Hosted (Railway / AWS):** set `OPENFDD_LOG_FORMAT=json` (compose default). Platform log retention is the volume cap; app JSON lines stay queryable (`event`, `request_id`, `channel=security_audit`).

For pen tests, ask operators for: `docker logs` (or Railway/AWS log export) filtered on `security_audit`, plus `workspace/logs/security_audit.jsonl*`.

## Python security harness (qualification evidence)

Reusable offline-first tooling lives under [`scripts/security/`](../../scripts/security/README.md).
It produces **scoped** evidence for named auth/JWT/authz/deployment checks for a
candidate + config + fixture set. It does **not** certify that Open-FDD is free of
vulnerabilities, and dry-run plans are never qualification PASS.

```bash
# Plan only (default): no network / no credential reads
python3 scripts/security/openfdd_security_probe.py \
  --config scripts/security/config/example_security_fixtures.json \
  --base-url http://127.0.0.1:18080 --profile isolated_full --dry-run

# Offline evaluator tests
python3 -B -m unittest discover -s tests/security -v
```

Stress gates (wired; live execute requires `OPENFDD_SECURITY_EXECUTE=1`):

| Gate ID | Script | Role |
| --- | --- | --- |
| `25_security_python_harness` | `25_security_python_harness.sh` | Pre-stress probe (≠ Wave L `25_wave_l_*`) |
| `25b_security_post_stress` | `25b_security_post_stress.sh` | Post-stress re-auth + bounded reads |
| `26_security_mqtt_acl` | `26_security_mqtt_acl.sh` | Optional broker ACL (≠ continuity gate 21) |

Evidence paths: `reports/security/` or per-run `ARTIFACT_DIR/gate25*_*/`.
Credentials are env refs only. Product findings stay private per [`SECURITY.md`](../../SECURITY.md).

## BACnet write safety

- `POST /api/bacnet/write-dry-run` before live writes
- Human approval required for production BACnet writes
- Agents must not write without explicit authorization

## Backup before change

Always back up `workspace/` before image updates or historian purges — see
[Backup, update, restore](backup-update-restore.html).

## Dependency scanning

Repository CI runs Rust audit, npm audit, Trivy, and Gitleaks on pull requests.
