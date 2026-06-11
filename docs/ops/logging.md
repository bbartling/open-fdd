---
title: Logging and audit
parent: Operations
nav_order: 5
---

# Logging and audit

Open-FDD uses a **two-tier logging model** familiar to IT and security teams: structured **audit/error JSONL** for forensics and compliance, plus **service stdout** for engineering troubleshooting. Defaults include **age pruning**, **size rotation in MB**, and **Docker log caps** — no operator cron required.

## Log types

| Tier | Location | Format | Who reads it |
|------|----------|--------|--------------|
| **Audit** | `workspace/logs/audit.jsonl` | JSON Lines | Security, MSI, integrator API |
| **Errors** | `workspace/logs/error.jsonl` | JSON Lines | Support, integrator API |
| **Service stdout** | Docker: `docker compose logs` · Dev: `workspace/.local-run/*.log` | Plain text (uvicorn, workers) | Engineering |
| **Historian** | `workspace/data/feather_store/` | Feather | FDD, plots — separate retention (`data.env.local`) |

Structured audit logs are **not** mixed into uvicorn access logs. That separation matches common practice: SIEM-friendly JSONL for auth and OT commands; unstructured stdout for stack traces and poll worker noise.

## Audit record schema

Each line in `audit.jsonl` / `error.jsonl` is one JSON object:

| Field | Example | Notes |
|-------|---------|-------|
| `@timestamp` | `2026-06-07T19:57:21+00:00` | UTC ISO-8601 |
| `event_id` | UUID | Unique per event |
| `event_type` | `auth.login.failure` | Stable taxonomy (see below) |
| `severity` | `warning` | `debug` … `critical` |
| `outcome` | `failure` | `success`, `failure`, `denied`, … |
| `service` | `openfdd-bridge` | |
| `host` | hostname | |
| `action` | `login` | Human-readable verb |
| `actor` | `{username, role}` | After successful auth |
| `client` | `{ip, user_agent}` | Respects `OFDD_TRUST_X_FORWARDED_FOR` behind Caddy |
| `http` | method, path, status | When HTTP-triggered |
| `resource` | BACnet object, model id, … | When applicable |
| `detail` | Sanitized map | **Passwords, tokens, secrets stripped by key name** |
| `request_id` | UUID | On audited HTTP paths |

### Auth events (industry-standard login trail)

| `event_type` | When |
|--------------|------|
| `auth.login.success` | Valid credentials |
| `auth.login.failure` | Bad password (generic client message) |
| `auth.login.lockout` | Rate limit exceeded (default 5 failures / 5 min) |

Login rate limits and lockouts are **audited**; responses never reveal whether the username exists.

### OT / commissioning events

| `event_type` | When |
|--------------|------|
| `bacnet.command` | Supervisory write (allowed, denied, dry-run) |
| `bacnet.discover` | Who-Is / point discovery |
| `model.write` | BRICK model mutations |
| `agent.tool` | Agent tool calls (prompts hashed/truncated) |
| `api.access` | Sensitive POST/PUT/PATCH/DELETE (BACnet, ingest) |
| `error.unhandled` | Unhandled exception (also in `error.jsonl`) |

**Not audited:** routine GETs (dashboard reads, plot data, health). This reduces noise while keeping **auth and field commands** on the trail.

### Secret redaction

Never logged: passwords, bearer tokens, `OFDD_AUTH_SECRET`, private keys. Detail objects drop keys containing `password`, `token`, `secret`, `authorization`. Agent tool arguments use additional hashing for prompts and rule source.

Opt-in full prompt logging (lab only): `OFDD_AUDIT_LOG_PROMPTS=1`.

## Integrator API (read logs in the UI stack)

| Method | Path | Role |
|--------|------|------|
| GET | `/api/audit/events?limit=100` | integrator |
| GET | `/api/audit/errors?limit=100` | integrator |
| GET | `/api/audit/summary` | integrator |

Use these for post-incident review without shell access. Forward `workspace/logs/*.jsonl` to SIEM (rsyslog, Filebeat, Wazuh) on production edges.

## Retention and rotation (defaults)

Configured in `workspace/data.env.local` (copy from `data.env.example`):

| Variable | Default | Behavior |
|----------|---------|----------|
| `OFDD_LOG_RETENTION_DAYS` | **90** | Drop audit/error JSONL lines older than N days; delete aged `.local-run` and archived `*.log` / `audit.*.jsonl` |
| `OFDD_LOG_MAX_MB` | **50** | When `audit.jsonl` or `error.jsonl` exceeds N MB, archive to `audit.{UTC}.jsonl` and start fresh |
| `OFDD_LOCAL_RUN_LOG_MAX_MB` | **25** | Rotate `workspace/.local-run/*.log` (bridge, Caddy, FDD loop, …) |
| `OFDD_LOG_ROTATE_INTERVAL_HOURS` | **6** | Background retention while bridge is running (not only at restart) |

Rotation runs at **bridge startup** and on the **scheduled interval**. No logrotate.d entry is required for audit JSONL.

Optional path overrides:

```bash
OFDD_AUDIT_LOG_PATH=/var/log/openfdd/audit.jsonl
OFDD_ERROR_LOG_PATH=/var/log/openfdd/error.jsonl
```

## Docker edge: json-file caps (not journald for app audit)

Production stacks use **Docker Compose** (`docker/compose.edge.yml`). Container stdout uses the **`json-file` driver with size limits**:

```yaml
logging:
  driver: json-file
  options:
    max-size: "25m"
    max-file: "5"
```

That caps each service at roughly **125 MB** of rotated container logs on disk — the same pattern many teams use instead of unbounded `docker logs`.

**Why audit JSONL stays on disk (not journald)?**

- Append-only files under `workspace/logs/` survive container recreate and bind-mount to the host.
- JSONL lines import cleanly into SIEM without journal field parsing.
- OT incident response often needs **months** of auth/BACnet write history on the edge box.

**When journald still applies:** native systemd units (Caddy, Ollama on bare metal) — use `journalctl -u <unit>` per your Linux runbook. Bridge audit remains in `workspace/logs/` even when uvicorn stdout goes to Docker or `.local-run/`.

## Local dev (`run_local.sh`)

| File | Service |
|------|---------|
| `workspace/.local-run/bridge.log` | Bridge / uvicorn |
| `workspace/.local-run/commission.log` | BACnet commission agent |
| `workspace/.local-run/caddy.log` | Caddy |
| `workspace/.local-run/fdd_loop.log` | Scheduled FDD |
| `workspace/.local-run/mcp_rag.log` | MCP RAG |
| `workspace/.local-run/ollama.log` | Ollama |

These are **engineering logs**. Structured audit still lands in `workspace/logs/audit.jsonl` when auth is enabled.

## Quick checks

```bash
# Last auth failures
grep 'auth.login' workspace/logs/audit.jsonl | tail -5

# Integrator API (after login)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/audit/summary | jq .

# Docker edge
docker compose logs bridge --tail 50
```

## Comparison to typical web apps

| Practice | Open-FDD |
|----------|----------|
| Structured auth audit | Yes — JSONL with actor, IP, outcome |
| Login rate limit + lockout audit | Yes |
| Secret redaction in logs | Yes — key-based + agent sanitization |
| Request correlation ID | Yes — on audited mutation paths |
| Centralized stdout JSON | No — stdout is plain text; audit is JSONL |
| Full HTTP access log | No — mutations and auth only (OT noise reduction) |
| Log rotation / size caps | Yes — defaults above + Docker `max-size` |
| SIEM-ready export | Yes — file tail / Filebeat on `workspace/logs/` |

For BACnet write safety and credential generation, see [SECURITY.md](https://github.com/bbartling/open-fdd/blob/master/workspace/deploy/SECURITY.md) and [Secrets and auth]({% link security/secrets-auth.md %}).

## Related

- [JSON API driver]({% link drivers/json-api.md %}) — OpenWeatherMap showcase, env-based API keys (`json_api.env.local`)
- [Live site update]({% link ops/live_site_update.md %}) — `docker compose logs` after upgrades
- [Data flow]({% link architecture/data-flow.md %}) — historian retention (`OFDD_FEATHER_*`) is separate from audit logs
