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
| **Security audit** | Login success/fail/throttle, command authz, command issue, telemetry suspend/resume, fieldbus API-key rejects | One JSONL file + stdout target `security_audit` |
| **App / error logs** | `tracing` at info/warn/error with `request_id` | stdout (Railway / AWS / `docker logs`) |

**File audit (local + volume mounts):**

```text
$OPENFDD_WORKSPACE/logs/security_audit.jsonl
```

Callers enqueue onto a bounded queue; a dedicated writer thread appends the
JSONL file (never on the request worker). Audit files live under the workspace
`logs/` directory — not in Timescale — and a guarded DB reset does not delete
them. There is no second database outbox for this file.

**Durability (`openfdd.audit.durability.v1`):**

Acknowledged events are denials and mutations. `log_event_acknowledged` returns
after the writer has appended that line and called `fsync`, or after it has
recorded a loss. Successful reads (`auth.bearer`, `admin.read`, `site.access`
when allowed) are best-effort: they are queued and are not fsynced per line.
Graceful shutdown flushes them.

SIGINT and SIGTERM let in-flight HTTP handlers finish, then close admission,
drain the writer, and fsync. The drain deadline is 5 seconds. A timeout is
logged. Best-effort events still in the queue at that deadline, and any
acknowledged line whose `fsync` has not finished, are the residual window for
a hard stop (SIGKILL or power loss). That window is not a graceful-shutdown
claim. Stdout is not the durability boundary.

Queue overflow (`OPENFDD_AUDIT_QUEUE_CAP`, default 1024, clamped 32..=16384)
drops a best-effort event immediately and increments `dropped`. That path does
not fsync once per drop. The loss file is sampled during the burst and fsynced
on shutdown. An acknowledged event waits `OPENFDD_AUDIT_ACK_MS` (default 2000,
clamped 50..=5000) and then records the same loss, and that record is fsynced.
Writer failures set `last_write_error` to `unwritable`
or `io` (never a path) and increment `write_failures`. Events refused because
admission is already closed increment `dropped_shutdown`.

`degraded` stays true while `dropped`, `dropped_shutdown`, or `write_failures`
is non-zero. A later successful write clears `last_write_error` only. Those
counters are stored in `security_audit.loss.json` (`openfdd.audit.loss.v1`)
and reloaded when the writer starts, so a process restart does not zero them.

Rotation defaults: `OPENFDD_AUDIT_LOG_MAX_BYTES=10485760` (10 MiB),
`OPENFDD_AUDIT_LOG_KEEP=5` (clamped 1..=32). Removing a generation increments
`rotated_out`. That is retention, not a loss, and does not set `degraded`.
Retained generations can be copied out as `openfdd.audit.export.v1`. Override
the path with `OPENFDD_AUDIT_LOG_PATH`. Secrets, passwords, tokens, and API
keys are redacted before the line is queued.

**Two copies of the line:** local size rotation on the JSONL file for
edge/LAN mounts, and the stdout `security_audit` tracing target for platforms
that scrape container logs. There is no network SIEM export and no legacy
`auth_audit.jsonl` dual-write. Platform, HTTP, service, and account audit
controls are separate from this file.

**Typed central events (`openfdd.audit.v1`):** each line keeps the
`{timestamp, channel, event, detail}` envelope; for central sensitive
operations `event` is the action and `detail` is a fixed-field record:

| Field | Meaning |
|-------|---------|
| `schema` | `openfdd.audit.v1` |
| `request_id` | Server-generated UUID, also returned as `x-openfdd-server-request-id` and stored on Actions rows started by that request |
| `caller_request_id` | Caller `x-request-id`, bounded (64 chars), never the primary key |
| `actor`, `auth_kind`, `role` | Subject, credential channel (`human_login` / `agent_token` / `anonymous`), and role |
| `identity` | `class` is `unique_human`, `shared_credential`, `agent_session`, or `anonymous`. `actor_id` is the user id or subject for a unique human, and null for a shared env credential (`admin`, `viewer`, or `agent` without a server session). `session_id` is a server UUID (`sid` on the token), not a hash of the bearer |
| `issued_session` | Present when this request minted a different session than the verified caller (an agent token). `delegated_by` is the parent session id |
| `qa_run` | Set only for an authenticated caller, and only from `OPENFDD_QA_RUN_MANIFEST`: run id, tenants, sites, tool version, candidate, and a UTC window that contains the current time. `server_approved` is that file. A client `qa_run` label is stored under `untrusted_labels` and grants no access |
| `untrusted_labels` | `user-agent`, `x-forwarded-for`, `x-openfdd-qa-run`, and `x-openfdd-actor`. Labels only |
| `correlation` | `server_request_id` plus job and receipt ids attached on this request |
| `tenant_id`, `site_id` | Resolved tenant and site (`building_id`) |
| `action`, `target_type`, `target_id` | See actions below; target is a user, tenant, site, action, or route |
| `decision`, `reason` | `allow` / `deny` and a fixed reason code (`missing_credentials`, `expired_token`, `role_required`, `site_scope`, `revision_conflict`, `size_cap`, …) |
| `outcome`, `http_status` | `ok` / `failed` / `partial` / `replayed`, recorded after the result is known |
| `change` | Typed summary (counts, ids, flags). Never request bodies, headers, or credentials |
| `build`, `method`, `path`, `ts`, `truncated` | Build version, request line (no query string), time, and whether size budgets dropped data |

Actions: `auth.login`, `auth.bearer`, `auth.agent_token`, `tenant.select`,
`site.access`, `admin.read`, `admin.maintenance`, `admin.historian_limits`,
`user.upsert`, `user.disable`, `user.delete`, `tenant.upsert`, `tenant.delete`,
`package.import`, `package.append`, `package.roles`, `session_config.put`,
`model.write`, `dataset.delete`, `actions.delete`, `actions.clear`, `fdd.run`,
`csv.export`.

Every string is length-bounded with a `…[truncated]` marker, control and
bidi characters are escaped, bearer/JWT/URL-query/`key=secret` fragments are
replaced with `[redacted]`, and the whole record is capped at 8 KiB. The same
sanitizer bounds free-form audit detail and the central panic hook line.
Tokens minted before these fields existed still verify; they omit `sid` and
are attributed as a shared credential when the subject is `agent`.

`ingest_job.server_request_id` and `ingest_receipt.server_request_id` are
nullable text columns added with `ADD COLUMN IF NOT EXISTS`. The id is stored
when the job is created inside a request and copied onto the receipt at
commit. A conflicting insert does not replace it. Scheduler work leaves it
null. `ingest_audit.detail` includes the same id for the request that wrote
the row. An older binary omits the column on insert; rolling back leaves the
column in place and unused. Existing rows stay null.

MCP sends `x-request-id` as its own label. It copies the response header
`x-openfdd-server-request-id` onto the tool result and replaces a body field
of that name. It does not send that header on the request.

**Container stdout rotation (GHCR compose / local Docker):**

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"
```

**Hosted:** set `OPENFDD_LOG_FORMAT=json` (compose default). Platform log retention is the volume cap; app JSON lines stay queryable (`event`, `request_id`, `channel=security_audit`). Those platform controls are not this file.

For pen tests, ask operators for container logs filtered on `security_audit`, plus `workspace/logs/security_audit.jsonl*` and `security_audit.loss.json`.

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
